"""Shared test fixtures: an app on a throw-away database, plus CSRF-aware request helpers."""

from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app
from app import security

TOKEN = "test-token"


class AppCase(unittest.TestCase):
    config_overrides: dict = {}

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = create_app({
            "DATA_DIR": self.root, "DATABASE_PATH": self.root / "test.db", "BACKUP_DIR": self.root / "backups",
            "LOG_DIR": self.root / "logs", "START_READER": False, "SECRET_KEY": "test-secret",
            **self.config_overrides})
        self.s = self.app.extensions["ssb"]
        security._attempts.clear()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- data helpers
    def book(self, name: str) -> dict:
        return next(b for b in self.s.books.list_with_status() if b["name"] == name)

    def day(self, name: str) -> dict:
        return next(d for d in self.s.timetable.days() if d["name"] == name)

    def card(self, name: str, uid: str) -> str:
        self.s.books.assign_uid(self.book(name)["id"], uid)
        return uid

    def no_debounce(self) -> None:
        self.s.settings.update({"debounce_seconds": 0})

    def scan(self, uid: str, source: str = "RFID") -> dict:
        return self.s.scans.process(uid, source)

    def state(self) -> dict:
        return self.s.state.snapshot()

    def sql(self, query: str, params=()):
        conn = sqlite3.connect(self.root / "test.db")
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()

    # ---- HTTP helpers
    def client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["csrf"] = TOKEN
        return client

    @staticmethod
    def post_json(client, url, payload=None, **kwargs):
        return client.post(url, json=payload if payload is not None else {}, headers={"X-CSRF-Token": TOKEN}, **kwargs)

    @staticmethod
    def post_form(client, url, data=None, **kwargs):
        return client.post(url, data={"csrf_token": TOKEN, **(data or {})}, **kwargs)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


__all__ = ["AppCase", "TOKEN", "read", "re"]
