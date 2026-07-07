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

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            # Общая статистика
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_count,
                    AVG(psq) as avg_psq,
                    SUM(CASE WHEN psq < 0.8 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as low_psq_ratio
                FROM history
            """)
            row = cursor.fetchone()
            stats = {
                "total_count": row["total_count"] or 0,
                "avg_psq": round(row["avg_psq"] or 0, 3),
                "low_psq_ratio": round(row["low_psq_ratio"] or 0, 3)
            }

            # Распределение по режимам
            cursor = conn.execute("SELECT mode, COUNT(*) as count FROM history GROUP BY mode")
            stats["modes"] = {row["mode"]: row["count"] for row in cursor.fetchall()}

            # Последние 20 оценок для графика
            cursor = conn.execute("SELECT timestamp, psq FROM history ORDER BY id DESC LIMIT 20")
            stats["recent_points"] = [{"timestamp": r["timestamp"], "psq": r["psq"]} for r in cursor.fetchall()][::-1]

            # Распределение флагов (прескрин)
            # Так как флаги хранятся в prescreen (вероятно как JSON строка или текст), 
            # а в add_entry передается res["prescreen"], нам нужно понять формат.
            # В main.py: res["flags"] = [{"name": f[0], "count": f[1]} for f in res["flags"]]
            # Но в базу пишется res["prescreen"].
            cursor = conn.execute("SELECT prescreen FROM history WHERE prescreen IS NOT NULL")
            flags_dist = {}
            for r in cursor.fetchall():
                try:
                    # Пытаемся распарсить если это JSON, иначе считаем как строку
                    data = json.loads(r["prescreen"])
                    if isinstance(data, dict) and "flags" in data:
                        for f in data["flags"]:
                            name = f[0] if isinstance(f, (list, tuple)) else f.get("name")
                            flags_dist[name] = flags_dist.get(name, 0) + 1
                except:
                    pass
            stats["flags_distribution"] = flags_dist

            return stats
