"""Ordered, idempotent schema migrations tracked with ``PRAGMA user_version``.

Rules: never drop user data; each migration runs in one transaction; add new
migrations to the end of ``MIGRATIONS``.
"""

from __future__ import annotations

import sqlite3

from .defaults import DEFAULT_BOOKS, DEFAULT_TIMETABLE
from .utils import utc_iso


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migration_1_baseline(conn: sqlite3.Connection) -> None:
    """The original v1 tables (no-ops on an existing v1 database)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        rfid_uid TEXT UNIQUE,
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rfid_uid TEXT NOT NULL,
        book_name TEXT,
        scanned_at TEXT NOT NULL,
        source TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL)""")


def migration_2_sessions_and_timetable(conn: sqlite3.Connection) -> None:
    """Packing sessions, database-driven timetable, book status, richer scan history."""
    now = utc_iso()
    legacy_timetable = "timetable" in _tables(conn)
    fresh = (conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
             and (not legacy_timetable or conn.execute("SELECT COUNT(*) FROM timetable").fetchone()[0] == 0))

    # books: disable flag + updated_at
    cols = _columns(conn, "books")
    if "is_active" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN updated_at TEXT")
        conn.execute("UPDATE books SET updated_at = created_at WHERE updated_at IS NULL")

    conn.execute("""CREATE TABLE IF NOT EXISTS timetable_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        position INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS timetable_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_id INTEGER NOT NULL REFERENCES timetable_days(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE RESTRICT,
        UNIQUE (day_id, position))""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_entries_book ON timetable_entries(book_id)")

    conn.execute("""CREATE TABLE IF NOT EXISTS packing_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_id INTEGER NOT NULL REFERENCES timetable_days(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'abandoned')),
        started_at TEXT NOT NULL,
        completed_at TEXT)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_one_active_session "
                 "ON packing_sessions(status) WHERE status = 'active'")
    conn.execute("""CREATE TABLE IF NOT EXISTS session_required_books (
        session_id INTEGER NOT NULL REFERENCES packing_sessions(id) ON DELETE CASCADE,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE RESTRICT,
        position INTEGER NOT NULL,
        PRIMARY KEY (session_id, book_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        level TEXT NOT NULL,
        category TEXT NOT NULL,
        message TEXT NOT NULL)""")

    # scan_history: link scans to sessions/books and record what the app decided
    cols = _columns(conn, "scan_history")
    if "session_id" not in cols:
        conn.execute("ALTER TABLE scan_history ADD COLUMN session_id INTEGER "
                     "REFERENCES packing_sessions(id) ON DELETE SET NULL")
    if "book_id" not in cols:
        conn.execute("ALTER TABLE scan_history ADD COLUMN book_id INTEGER "
                     "REFERENCES books(id) ON DELETE SET NULL")
    if "outcome" not in cols:
        conn.execute("ALTER TABLE scan_history ADD COLUMN outcome TEXT")
        # Legacy rows: link to books by name where we can; outcome stays NULL ("legacy").
        conn.execute("""UPDATE scan_history SET book_id =
            (SELECT b.id FROM books b WHERE b.name = scan_history.book_name COLLATE NOCASE)
            WHERE book_name IS NOT NULL AND book_id IS NULL""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_time ON scan_history(scanned_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_session ON scan_history(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_source ON scan_history(source)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_scans_book ON scan_history(book_id)")

    if fresh:
        for name in DEFAULT_BOOKS:
            conn.execute("INSERT INTO books(name, rfid_uid, created_at, updated_at) VALUES (?, NULL, ?, ?)",
                         (name, now, now))
        for day_position, (day, subjects) in enumerate(DEFAULT_TIMETABLE.items(), start=1):
            day_id = conn.execute("INSERT INTO timetable_days(name, position) VALUES (?, ?)",
                                  (day, day_position)).lastrowid
            for period, subject in enumerate(subjects, start=1):
                book_id = conn.execute("SELECT id FROM books WHERE name = ?", (subject,)).fetchone()[0]
                conn.execute("INSERT INTO timetable_entries(day_id, position, book_id) VALUES (?, ?, ?)",
                             (day_id, period, book_id))
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('selected_day', ?)", ('"Monday"',))
    elif legacy_timetable:
        # Existing install: convert the free-text timetable into day/book relations.
        rows = conn.execute("SELECT day, period, subject FROM timetable ORDER BY id").fetchall()
        day_ids: dict[str, int] = {}
        for row in rows:
            day = row["day"].strip()
            if day.casefold() not in day_ids:
                existing = conn.execute("SELECT id FROM timetable_days WHERE name = ?", (day,)).fetchone()
                day_ids[day.casefold()] = existing[0] if existing else conn.execute(
                    "INSERT INTO timetable_days(name, position) VALUES (?, ?)",
                    (day, len(day_ids) + 1)).lastrowid
        for row in rows:
            subject = row["subject"].strip()
            book = conn.execute("SELECT id FROM books WHERE name = ?", (subject,)).fetchone()
            book_id = book[0] if book else conn.execute(
                "INSERT INTO books(name, rfid_uid, created_at, updated_at) VALUES (?, NULL, ?, ?)",
                (subject, now, now)).lastrowid
            conn.execute("INSERT OR IGNORE INTO timetable_entries(day_id, position, book_id) VALUES (?, ?, ?)",
                         (day_ids[row["day"].strip().casefold()], row["period"], book_id))
    # The legacy `timetable` table is intentionally left in place (deprecated, unused).


MIGRATIONS = [
    (1, migration_1_baseline),
    (2, migration_2_sessions_and_timetable),
]
LATEST_VERSION = MIGRATIONS[-1][0]
