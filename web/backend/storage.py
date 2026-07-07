import sqlite3
import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

class HistoryStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    prompt TEXT NOT NULL,
                    psq REAL,
                    gaming REAL,
                    prescreen TEXT,
                    mode TEXT
                )
            """)
            conn.commit()

    def add_entry(self, prompt: str, psq: float, gaming: float, prescreen: Optional[str], mode: str):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO history (prompt, psq, gaming, prescreen, mode) VALUES (?, ?, ?, ?, ?)",
                (prompt, psq, gaming, prescreen, mode)
            )
            conn.commit()

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, timestamp, prompt, psq, gaming, prescreen, mode FROM history ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_entry(self, entry_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, timestamp, prompt, psq, gaming, prescreen, mode FROM history WHERE id = ?",
                (entry_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def clear_history(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM history")
            conn.commit()
