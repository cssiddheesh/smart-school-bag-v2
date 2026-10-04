"""SQL for the bounded ``system_events`` table."""

from __future__ import annotations

import sqlite3

MAX_EVENTS = 1000


def add(conn: sqlite3.Connection, ts: str, level: str, category: str, message: str) -> None:
    conn.execute("INSERT INTO system_events(ts, level, category, message) VALUES (?, ?, ?, ?)",
                 (ts, level, category, message[:500]))
    conn.execute("DELETE FROM system_events WHERE id <= (SELECT MAX(id) FROM system_events) - ?", (MAX_EVENTS,))


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute("SELECT id, ts, level, category, message FROM system_events ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
    return [dict(r) for r in rows]
