"""Writes notable events to the log AND the ``system_events`` table (never raises)."""

from __future__ import annotations

import logging
import sqlite3

from ..db import Database
from ..repositories import events as repo
from ..utils import utc_iso

log = logging.getLogger("ssb.events")


class EventService:
    def __init__(self, db: Database):
        self.db = db

    def log(self, level: str, category: str, message: str) -> None:
        log.log({"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO),
                "[%s] %s", category, message)
        try:
            with self.db.write() as conn:
                repo.add(conn, utc_iso(), level, category, message)
        except sqlite3.Error:
            log.exception("Could not store system event")

    def recent(self, limit: int = 20) -> list[dict]:
        with self.db.read() as conn:
            return repo.recent(conn, limit)
