"""Сессии spt: sqlite ~/.spt/sessions.db (уровень 1 памяти — контекст)."""
import datetime
import json
import os
import sqlite3
import uuid

from . import config

DB = os.path.join(config.SPT_DIR, "sessions.db")


def _con():
    config.ensure_dir()                    # 0700 каталог (переписка/секреты — не world-readable)
    new_db = not os.path.exists(DB)
    con = sqlite3.connect(DB, timeout=10)  # параллельный spt run/cron не должен ронять REPL
    if new_db:
        config.harden_file(DB)             # 0600: история сессий приватна
    con.execute("""create table if not exists sessions(
        id text primary key, title text, created text, updated text)""")
    con.execute("""create table if not exists messages(
        session_id text, n integer, role text, data text)""")
    return con


# T7: битая/занятая база НЕ должна ронять REPL (журнал не важнее работы терминала).
# Каждая операция деградирует безопасно: new → in-memory sid, чтения → пусто.
def new(title=""):
    sid = "spt_" + uuid.uuid4().hex[:12]
    try:
        con = _con()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        con.execute("insert into sessions values(?,?,?,?)", (sid, title[:120], now, now))
        con.commit()
    except (sqlite3.Error, OSError):
        pass  # сессия не сохранится, но терминал поднимется с валидным sid
    return sid


def append(sid, msgs, start_n):
    try:
        con = _con()
        for i, m in enumerate(msgs):
            con.execute("insert into messages values(?,?,?,?)",
                        (sid, start_n + i, m["role"], json.dumps(m, ensure_ascii=False)))
        con.execute("update sessions set updated=? where id=?",
                    (datetime.datetime.now().isoformat(timespec="seconds"), sid))
        con.commit()
    except (sqlite3.Error, OSError):
        pass


def next_n(sid):
    """Следующий свободный индекс сообщения в сессии (чтобы append не накладывался)."""
    try:
        con = _con()
        row = con.execute("select max(n) from messages where session_id=?",
                          (sid,)).fetchone()
        return 0 if row[0] is None else row[0] + 1
    except (sqlite3.Error, OSError):
        return 0


def load(sid):
    try:
        con = _con()
        rows = con.execute("select data from messages where session_id=? order by n",
                           (sid,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    except (sqlite3.Error, OSError, ValueError):
        return []


def last_sessions(n=10):
    try:
        con = _con()
        return con.execute("select id,title,updated from sessions "
                           "order by updated desc limit ?", (n,)).fetchall()
    except (sqlite3.Error, OSError):
        return []
