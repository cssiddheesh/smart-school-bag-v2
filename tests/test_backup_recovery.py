import io
import unittest

from app import create_app
from app.errors import NotFoundError, ValidationError
from tests.helpers import AppCase


class BackupTests(AppCase):
    def test_backup_restores_earlier_state_and_keeps_a_safety_copy(self):
        backup = self.s.backup.create("manual")
        self.s.books.add("Geography")
        self.s.backup.restore_named(backup.name)
        names = [b["name"] for b in self.s.books.list_with_status()]
        self.assertNotIn("Geography", names)
        self.assertEqual(len(list((self.root / "backups").glob("*pre-restore.db"))), 1)
        self.assertEqual(self.sql("PRAGMA integrity_check")[0][0], "ok")

    def test_only_server_generated_names_are_accepted(self):
        for bad in ("../test.db", "..%2Ftest.db", "schoolbag-1.db", "/etc/passwd", "", "schoolbag-20260101-000000.db.exe"):
            with self.assertRaises(NotFoundError, msg=bad):
                self.s.backup.path_for(bad)

    def test_validation_rejects_non_databases_and_foreign_databases(self):
        fake = self.root / "fake.db"
        fake.write_bytes(b"hello")
        with self.assertRaises(ValidationError):
            self.s.backup.validate(fake)
        import sqlite3
        foreign = self.root / "foreign.db"
        conn = sqlite3.connect(foreign)
        conn.execute("CREATE TABLE other (x)")
        conn.commit()
        conn.close()
        with self.assertRaises(ValidationError):
            self.s.backup.validate(foreign)

    def test_upload_restore_over_http(self):
        c = self.client()
        backup = self.s.backup.create("manual")
        self.s.books.add("Geography")
        r = c.post("/backups/upload", data={"csrf_token": "test-token", "backup_file": (io.BytesIO(backup.read_bytes()), "b.db")},
                   content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Backup restored", r.get_data(as_text=True))
        self.assertNotIn("Geography", [b["name"] for b in self.s.books.list_with_status()])
        bad = c.post("/backups/upload", data={"csrf_token": "test-token", "backup_file": (io.BytesIO(b"junk"), "b.db")},
                     content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("not a SQLite database", bad.get_data(as_text=True))

    def test_download_and_manage_over_http(self):
        c = self.client()
        self.post_form(c, "/backups/create")
        name = self.s.backup.list()[0]["name"]
        with c.get(f"/backups/{name}/download") as download:
            self.assertEqual(download.status_code, 200)
            self.assertTrue(download.data.startswith(b"SQLite format 3"))
        self.assertEqual(c.get("/backups/..%2Fx.db/download").status_code, 404)
        self.post_form(c, f"/backups/{name}/delete")
        self.assertEqual(self.s.backup.list(), [])

    def test_automatic_backups_are_pruned_but_manual_ones_are_not(self):
        manual = self.s.backup.create("manual")
        for _ in range(14):
            self.s.backup.create("pre-clear")
        files = [p.name for p in (self.root / "backups").glob("*.db")]
        self.assertEqual(len([f for f in files if "pre-clear" in f]), 10)
        self.assertTrue(manual.exists())


class RecoveryModeTests(AppCase):
    def make_corrupt_app(self):
        path = self.root / "broken.db"
        path.write_bytes(b"garbage" * 200)
        return create_app({"DATA_DIR": self.root, "DATABASE_PATH": path, "BACKUP_DIR": self.root / "backups",
                           "LOG_DIR": self.root / "logs", "START_READER": False}), path

    def test_corrupt_database_starts_recovery_mode_and_is_not_overwritten(self):
        app, path = self.make_corrupt_app()
        self.assertTrue(app.config["DB_ERROR"]["corrupt"])
        c = app.test_client()
        for url in ("/", "/books", "/history"):
            r = c.get(url)
            self.assertEqual(r.status_code, 503)
            self.assertIn("needs attention", r.get_data(as_text=True))
            self.assertNotIn("Traceback", r.get_data(as_text=True))
        self.assertEqual(c.get("/api/state").get_json()["error"]["code"], "database_unavailable")
        self.assertEqual(c.get("/healthz").status_code, 503)
        self.assertTrue(path.read_bytes().startswith(b"garbage"))

    def test_recover_by_restoring_a_backup(self):
        good = self.s.backup.create("manual")
        app, path = self.make_corrupt_app()
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["csrf"] = "test-token"
        r = c.post("/recovery/restore", data={"csrf_token": "test-token", "name": good.name}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(app.config["DB_ERROR"])
        self.assertEqual(c.get("/").status_code, 200)
        self.assertEqual(len(list(self.root.glob("broken.corrupt-*"))), 1)  # damaged file kept aside

    def test_start_fresh_keeps_the_damaged_file(self):
        app, path = self.make_corrupt_app()
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["csrf"] = "test-token"
        c.post("/recovery/fresh", data={"csrf_token": "test-token"})
        self.assertIsNone(app.config["DB_ERROR"])
        self.assertEqual(app.extensions["ssb"].books.list_with_status()[0]["is_active"], 1)
        self.assertEqual(len(list(self.root.glob("broken.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
