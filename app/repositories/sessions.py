"""SQL for packing sessions."""

from __future__ import annotations

import sqlite3
from typing import Optional

_SELECT = """SELECT s.id, s.day_id, s.status, s.started_at, s.completed_at, d.name AS day_name
             FROM packing_sessions s JOIN timetable_days d ON d.id = s.day_id"""


def get_active(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(f"{_SELECT} WHERE s.status = 'active'").fetchone()
    return dict(row) if row else None


def get(conn: sqlite3.Connection, session_id: int) -> Optional[dict]:
    row = conn.execute(f"{_SELECT} WHERE s.id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def last_finished(conn: sqlite3.Connection) -> Optional[dict]:
    row = conn.execute(f"{_SELECT} WHERE s.status != 'active' ORDER BY s.id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def create(conn: sqlite3.Connection, day_id: int, required: list[dict], now: str) -> int:
    session_id = conn.execute(
        "INSERT INTO packing_sessions(day_id, status, started_at) VALUES (?, 'active', ?)",
        (day_id, now)).lastrowid
    conn.executemany(
        "INSERT INTO session_required_books(session_id, book_id, position) VALUES (?, ?, ?)",
        [(session_id, item["book_id"], index) for index, item in enumerate(required, start=1)])
    return session_id


def set_status(conn: sqlite3.Connection, session_id: int, status: str, now: str) -> None:
    conn.execute("UPDATE packing_sessions SET status = ?, completed_at = ? WHERE id = ?", (status, now, session_id))


def required_books(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT b.id AS book_id, b.name AS name
           FROM session_required_books r JOIN books b ON b.id = r.book_id
           WHERE r.session_id = ? ORDER BY r.position""", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def search(conn: sqlite3.Connection, *, day_id: Optional[int], status: Optional[str],
           limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = [], []
    if day_id:
        where.append("s.day_id = ?")
        params.append(day_id)
    if status:
        where.append("s.status = ?")
        params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM packing_sessions s {clause}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT s.id, s.status, s.started_at, s.completed_at, d.name AS day_name,
              (SELECT COUNT(*) FROM session_required_books r WHERE r.session_id = s.id) AS required_count,
              (SELECT COUNT(DISTINCT c.book_id) FROM scan_history c
                 WHERE c.session_id = s.id AND c.outcome = 'accepted') AS packed_count,
              (SELECT COUNT(*) FROM scan_history c WHERE c.session_id = s.id) AS scan_count,
              (SELECT COUNT(*) FROM scan_history c WHERE c.session_id = s.id AND c.source = 'SIMULATION') AS simulated_count
            FROM packing_sessions s JOIN timetable_days d ON d.id = s.day_id
            {clause} ORDER BY s.id DESC LIMIT ? OFFSET ?""", [*params, limit, offset]).fetchall()
    return [dict(r) for r in rows], total
