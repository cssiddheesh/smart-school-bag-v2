"""SQL for the ``books`` table. Functions take an open connection."""

from __future__ import annotations

import sqlite3
from typing import Optional

_COLS = "id, name, rfid_uid, is_active, created_at, updated_at"


def _row(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {_COLS} FROM books ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def list_active(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {_COLS} FROM books WHERE is_active = 1 ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def get(conn: sqlite3.Connection, book_id: int) -> Optional[dict]:
    return _row(conn.execute(f"SELECT {_COLS} FROM books WHERE id = ?", (book_id,)).fetchone())


def get_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    return _row(conn.execute(f"SELECT {_COLS} FROM books WHERE name = ? COLLATE NOCASE", (name,)).fetchone())


def get_by_uid(conn: sqlite3.Connection, uid: str) -> Optional[dict]:
    return _row(conn.execute(f"SELECT {_COLS} FROM books WHERE rfid_uid = ?", (uid,)).fetchone())


def create(conn: sqlite3.Connection, name: str, now: str) -> int:
    return conn.execute(
        "INSERT INTO books(name, rfid_uid, is_active, created_at, updated_at) VALUES (?, NULL, 1, ?, ?)",
        (name, now, now)).lastrowid


def rename(conn: sqlite3.Connection, book_id: int, name: str, now: str) -> None:
    conn.execute("UPDATE books SET name = ?, updated_at = ? WHERE id = ?", (name, now, book_id))


def set_active(conn: sqlite3.Connection, book_id: int, active: bool, now: str) -> None:
    conn.execute("UPDATE books SET is_active = ?, updated_at = ? WHERE id = ?", (1 if active else 0, now, book_id))


def set_uid(conn: sqlite3.Connection, book_id: int, uid: Optional[str], now: str) -> None:
    conn.execute("UPDATE books SET rfid_uid = ?, updated_at = ? WHERE id = ?", (uid, now, book_id))


def usage(conn: sqlite3.Connection, book_id: int) -> dict[str, int]:
    return {
        "timetable": conn.execute("SELECT COUNT(*) FROM timetable_entries WHERE book_id = ?", (book_id,)).fetchone()[0],
        "sessions": conn.execute("SELECT COUNT(*) FROM session_required_books WHERE book_id = ?", (book_id,)).fetchone()[0],
        "scans": conn.execute("SELECT COUNT(*) FROM scan_history WHERE book_id = ?", (book_id,)).fetchone()[0],
    }


def delete(conn: sqlite3.Connection, book_id: int) -> None:
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
