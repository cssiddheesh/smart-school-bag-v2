import sqlite3
import unittest
from pathlib import Path

from app import create_app
from app.db import Database, initialize
from app.errors import DatabaseStartupError
from app.migrations import LATEST_VERSION
from tests.helpers import AppCase

import tempfile


def make_v1_database(path: Path) -> None:
    """The original (v1) schema with realistic data, including stale session state."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            rfid_uid TEXT UNIQUE, created_at TEXT NOT NULL);
        CREATE TABLE timetable (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, period INTEGER NOT NULL,
                                subject TEXT NOT NULL, UNIQUE(day, period));
        CREATE TABLE scan_history (id INTEGER PRIMARY KEY AUTOINCREMENT, rfid_uid TEXT NOT NULL, book_name TEXT,
                                   scanned_at TEXT NOT NULL, source TEXT NOT NULL);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO books VALUES (1,'English','ABCD1234','2026-01-01T00:00:00+00:00'),(2,'Maths',NULL,'2026-01-01T00:00:00+00:00');
        INSERT INTO timetable(day,period,subject) VALUES ('Monday',1,'English'),('Monday',2,'Maths'),
            ('Monday',3,'Drawing'),('Tuesday',1,'maths');
        INSERT INTO scan_history(rfid_uid,book_name,scanned_at,source) VALUES
            ('ABCD1234','English','2026-01-02T08:00:00+00:00','RFID'),('DEMOMATHS','Maths','2026-01-02T08:01:00+00:00','SIMULATION');
        INSERT INTO settings VALUES ('selected_day','"Tuesday"'),('detected_books','["English","Maths"]');
    """)
    conn.commit()
    conn.close()


class FreshDatabaseTests(AppCase):
    def test_new_database_is_seeded_once_with_the_demo_timetable(self):
        self.assertEqual(len(self.s.books.list_with_status()), 5)
        self.assertEqual([d["name"] for d in self.s.timetable.days()], ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.assertEqual(self.s.timetable.day_view(self.day("Monday")["id"])["required"][0]["name"], "English")

    def test_restart_keeps_data_and_never_reseeds_deleted_items(self):
        monday = self.day("Monday")["id"]
        entry = self.s.timetable.day_view(monday)["entries"][0]["id"]
        self.s.timetable.remove_entry(entry)
        self.s.books.add("Art")
        initialize(self.s.db, self.root / "backups")  # simulate restart
        self.assertEqual(len(self.s.timetable.day_view(monday)["entries"]), 4)
        self.assertIn("Art", [b["name"] for b in self.s.books.list_with_status()])
        self.assertEqual(self.sql("PRAGMA user_version")[0][0], LATEST_VERSION)

    def test_new_app_instance_sees_persisted_data(self):
        self.s.books.add("Geography")
        again = create_app({"DATA_DIR": self.root, "DATABASE_PATH": self.root / "test.db",
                            "BACKUP_DIR": self.root / "backups", "LOG_DIR": self.root / "logs", "START_READER": False})
        self.assertIn("Geography", [b["name"] for b in again.extensions["ssb"].books.list_with_status()])

    def test_database_enforces_foreign_keys_and_uniqueness(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s.db.write() as conn:
                conn.execute("INSERT INTO timetable_entries(day_id, position, book_id) VALUES (999, 1, 1)")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s.db.write() as conn:
                conn.execute("INSERT INTO books(name, created_at) VALUES ('english', 'x')")

    def test_only_one_active_session_is_possible(self):
        self.s.sessions.start()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s.db.write() as conn:
                conn.execute("INSERT INTO packing_sessions(day_id, status, started_at) VALUES (1, 'active', 'x')")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "legacy.db"
        make_v1_database(self.path)
        self.db = Database(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_v1_database_is_upgraded_without_losing_anything(self):
        initialize(self.db, self.root / "backups")
        with self.db.read() as conn:
            days = {r["name"]: r["n"] for r in conn.execute(
                "SELECT d.name, COUNT(e.id) n FROM timetable_days d JOIN timetable_entries e ON e.day_id = d.id GROUP BY d.id")}
            books = {r["name"]: r["rfid_uid"] for r in conn.execute("SELECT name, rfid_uid FROM books")}
            scans = conn.execute("SELECT COUNT(*), COUNT(book_id) FROM scan_history").fetchone()
            selected = conn.execute("SELECT value FROM settings WHERE key = 'selected_day'").fetchone()[0]
            legacy_rows = conn.execute("SELECT COUNT(*) FROM timetable").fetchone()[0]
        self.assertEqual(days, {"Monday": 3, "Tuesday": 1})
        self.assertEqual(books["English"], "ABCD1234")            # card assignment kept
        self.assertIn("Drawing", books)                           # unknown subject became a book
        self.assertEqual(tuple(scans), (2, 2))                    # history kept and linked to books
        self.assertEqual(selected, '"Tuesday"')                   # existing settings kept
        self.assertEqual(legacy_rows, 4)                          # legacy table left in place
        self.assertEqual(len(list((self.root / "backups").glob("*auto-upgrade.db"))), 1)

    def test_case_variant_subject_maps_to_existing_book(self):
        initialize(self.db, self.root / "backups")
        with self.db.read() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM books WHERE name = 'maths' COLLATE NOCASE").fetchone()[0], 1)

    def test_upgrade_is_idempotent(self):
        initialize(self.db, self.root / "backups")
        initialize(self.db, self.root / "backups")
        self.assertEqual(len(list((self.root / "backups").glob("*.db"))), 1)  # no second backup: nothing pending

    def test_newer_schema_is_refused_not_modified(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()
        with self.assertRaises(DatabaseStartupError) as ctx:
            initialize(self.db, self.root / "backups")
        self.assertFalse(ctx.exception.corrupt)

    def test_garbage_file_is_reported_as_corrupt_and_left_untouched(self):
        garbage = self.root / "bad.db"
        garbage.write_bytes(b"this is definitely not a database" * 50)
        with self.assertRaises(DatabaseStartupError) as ctx:
            initialize(Database(garbage), self.root / "backups")
        self.assertTrue(ctx.exception.corrupt)
        self.assertTrue(garbage.read_bytes().startswith(b"this is definitely"))


if __name__ == "__main__":
    unittest.main()
