"""SQL for scan history."""

from __future__ import annotations

import sqlite3
from typing import Optional

_COLS = ("c.id, c.rfid_uid, c.book_name, c.scanned_at, c.source, c.session_id, c.book_id, c.outcome, "
         "d.name AS day_name")
_FROM = ("FROM scan_history c LEFT JOIN packing_sessions s ON s.id = c.session_id "
         "LEFT JOIN timetable_days d ON d.id = s.day_id")


def insert(conn: sqlite3.Connection, *, uid: str, book_name: Optional[str], book_id: Optional[int],
           source: str, session_id: Optional[int], outcome: str, now: str) -> int:
    return conn.execute(
        """INSERT INTO scan_history(rfid_uid, book_name, scanned_at, source, session_id, book_id, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uid, book_name, now, source, session_id, book_id, outcome)).lastrowid


def get(conn: sqlite3.Connection, scan_id: int) -> Optional[dict]:
    row = conn.execute(f"SELECT {_COLS} {_FROM} WHERE c.id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None


def book_outcomes(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """Books counted in a session (accepted or not-required), oldest first."""
    rows = conn.execute(
        """SELECT book_id, book_name, outcome, MIN(id) AS first_id
           FROM scan_history
           WHERE session_id = ? AND book_id IS NOT NULL AND outcome IN ('accepted', 'not_required')
           GROUP BY book_id, outcome ORDER BY first_id""", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def has_counted(conn: sqlite3.Connection, session_id: int, book_id: int, outcome: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM scan_history WHERE session_id = ? AND book_id = ? AND outcome = ? LIMIT 1",
        (session_id, book_id, outcome)).fetchone() is not None


def last_in_session(conn: sqlite3.Connection, session_id: int) -> Optional[dict]:
    row = conn.execute(f"SELECT {_COLS} {_FROM} WHERE c.session_id = ? ORDER BY c.id DESC LIMIT 1",
                       (session_id,)).fetchone()
    return dict(row) if row else None


def last_since(conn: sqlite3.Connection, since_iso: str) -> Optional[dict]:
    row = conn.execute(f"SELECT {_COLS} {_FROM} WHERE c.scanned_at >= ? ORDER BY c.id DESC LIMIT 1",
                       (since_iso,)).fetchone()
    return dict(row) if row else None


def for_session(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(f"SELECT {_COLS} {_FROM} WHERE c.session_id = ? ORDER BY c.id", (session_id,)).fetchall()
    return [dict(r) for r in rows]


def session_counts(conn: sqlite3.Connection, session_id: int) -> dict:
    rows = conn.execute(
        "SELECT outcome, source, COUNT(*) AS n FROM scan_history WHERE session_id = ? GROUP BY outcome, source",
        (session_id,)).fetchall()
    counts = {"total": 0, "accepted": 0, "duplicate": 0, "not_required": 0, "unknown_card": 0,
              "simulated": 0, "real": 0}
    for row in rows:
        counts["total"] += row["n"]
        if row["outcome"] in counts:
            counts[row["outcome"]] += row["n"]
        counts["simulated" if row["source"] == "SIMULATION" else "real"] += row["n"]
    return counts


def search(conn: sqlite3.Connection, *, query: str = "", day_id: Optional[int] = None,
           session_id: Optional[int] = None, source: Optional[str] = None,
           outcome: Optional[str] = None, limit: int = 25, offset: int = 0) -> tuple[list[dict], int]:
    where, params = [], []
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("c.book_name LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    if day_id:
        where.append("s.day_id = ?")
        params.append(day_id)
    if session_id:
        where.append("c.session_id = ?")
        params.append(session_id)
    if source:
        where.append("c.source = ?")
        params.append(source)
    if outcome == "legacy":
        where.append("c.outcome IS NULL")
    elif outcome:
        where.append("c.outcome = ?")
        params.append(outcome)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) {_FROM} {clause}", params).fetchone()[0]
    rows = conn.execute(f"SELECT {_COLS} {_FROM} {clause} ORDER BY c.id DESC LIMIT ? OFFSET ?",
                        [*params, limit, offset]).fetchall()
    return [dict(r) for r in rows], total


def totals(conn: sqlite3.Connection) -> dict:
    return {
        "scans": conn.execute("SELECT COUNT(*) FROM scan_history").fetchone()[0],
        "books": conn.execute("SELECT COUNT(DISTINCT book_id) FROM scan_history WHERE book_id IS NOT NULL").fetchone()[0],
        "completed": conn.execute("SELECT COUNT(*) FROM packing_sessions WHERE status = 'completed'").fetchone()[0],
        "sessions": conn.execute("SELECT COUNT(*) FROM packing_sessions").fetchone()[0],
    }


def clear(conn: sqlite3.Connection, keep_session_id: Optional[int]) -> int:
    """Delete scans and finished sessions; an active session is preserved."""
    if keep_session_id is None:
        removed = conn.execute("DELETE FROM scan_history").rowcount
    else:
        removed = conn.execute("DELETE FROM scan_history WHERE session_id IS NULL OR session_id != ?",
                               (keep_session_id,)).rowcount
    conn.execute("DELETE FROM packing_sessions WHERE status != 'active'")
    return removed
