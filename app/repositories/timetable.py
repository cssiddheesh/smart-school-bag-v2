"""SQL for timetable days and their ordered entries (periods)."""

from __future__ import annotations

import sqlite3
from typing import Optional


def list_days(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, position FROM timetable_days ORDER BY position, id").fetchall()
    return [dict(r) for r in rows]


def get_day(conn: sqlite3.Connection, day_id: int) -> Optional[dict]:
    row = conn.execute("SELECT id, name, position FROM timetable_days WHERE id = ?", (day_id,)).fetchone()
    return dict(row) if row else None


def get_day_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    row = conn.execute("SELECT id, name, position FROM timetable_days WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return dict(row) if row else None


def create_day(conn: sqlite3.Connection, name: str) -> int:
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM timetable_days").fetchone()[0]
    return conn.execute("INSERT INTO timetable_days(name, position) VALUES (?, ?)", (name, position)).lastrowid


def rename_day(conn: sqlite3.Connection, day_id: int, name: str) -> None:
    conn.execute("UPDATE timetable_days SET name = ? WHERE id = ?", (name, day_id))


def delete_day(conn: sqlite3.Connection, day_id: int) -> None:
    conn.execute("DELETE FROM timetable_days WHERE id = ?", (day_id,))


def day_session_count(conn: sqlite3.Connection, day_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM packing_sessions WHERE day_id = ?", (day_id,)).fetchone()[0]


def renumber_days(conn: sqlite3.Connection, ordered_ids: list[int]) -> None:
    for position, day_id in enumerate(ordered_ids, start=1):
        conn.execute("UPDATE timetable_days SET position = ? WHERE id = ?", (position, day_id))


def entries(conn: sqlite3.Connection, day_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT e.id, e.position, e.book_id, b.name AS book_name, b.is_active
           FROM timetable_entries e JOIN books b ON b.id = e.book_id
           WHERE e.day_id = ? ORDER BY e.position""", (day_id,)).fetchall()
    return [dict(r) for r in rows]


def get_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[dict]:
    row = conn.execute("SELECT id, day_id, position, book_id FROM timetable_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def required_books(conn: sqlite3.Connection, day_id: int) -> list[dict]:
    """Distinct *active* books needed on a day, in first-period order."""
    rows = conn.execute(
        """SELECT b.id AS book_id, b.name AS name, MIN(e.position) AS first_position
           FROM timetable_entries e JOIN books b ON b.id = e.book_id
           WHERE e.day_id = ? AND b.is_active = 1
           GROUP BY b.id ORDER BY first_position""", (day_id,)).fetchall()
    return [{"book_id": r["book_id"], "name": r["name"]} for r in rows]


def add_entry(conn: sqlite3.Connection, day_id: int, book_id: int) -> int:
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM timetable_entries WHERE day_id = ?",
                            (day_id,)).fetchone()[0]
    return conn.execute("INSERT INTO timetable_entries(day_id, position, book_id) VALUES (?, ?, ?)",
                        (day_id, position, book_id)).lastrowid


def set_entry_book(conn: sqlite3.Connection, entry_id: int, book_id: int) -> None:
    conn.execute("UPDATE timetable_entries SET book_id = ? WHERE id = ?", (book_id, entry_id))


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM timetable_entries WHERE id = ?", (entry_id,))


def renumber_entries(conn: sqlite3.Connection, day_id: int, ordered_ids: list[int]) -> None:
    """Rewrite periods 1..n without tripping UNIQUE(day_id, position)."""
    conn.execute("UPDATE timetable_entries SET position = -id WHERE day_id = ?", (day_id,))
    for position, entry_id in enumerate(ordered_ids, start=1):
        conn.execute("UPDATE timetable_entries SET position = ? WHERE id = ?", (position, entry_id))
