"""Validated, cached application settings stored in the database."""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any, Callable

from ..bus import StateBus
from ..db import Database
from ..errors import ValidationError
from ..repositories import settings as repo
from ..repositories import timetable as timetable_repo
from ..utils import DEFAULT_TIMEZONE, clean_text, is_valid_timezone, to_int

log = logging.getLogger("ssb.settings")

READER_TYPES = ("none", "keyboard", "serial")
BAUD_RATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)

DEFAULTS: dict[str, Any] = {
    "school_name": "My School",
    "student_name": "",
    "default_day": "Monday",
    "selected_day": "Monday",
    "timezone": DEFAULT_TIMEZONE,
    "demo_enabled": True,
    "reader_type": "none",
    "reader_device": "",
    "reader_baud": 9600,
    "auto_start_session": True,
    "debounce_seconds": 3,
    "admin_pin": "",
}
READER_KEYS = {"reader_type", "reader_device", "reader_baud"}


class SettingsService:
    def __init__(self, db: Database, bus: StateBus):
        self.db = db
        self.bus = bus
        self._cache: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[set[str]], None]] = []

    def add_listener(self, listener: Callable[[set[str]], None]) -> None:
        self._listeners.append(listener)

    def get_all(self) -> dict[str, Any]:
        """All settings merged over defaults. Falls back to defaults if the database is unreadable."""
        with self._lock:
            if self._cache is not None:
                return dict(self._cache)
        try:
            with self.db.read() as conn:
                stored = repo.get_all(conn)
        except sqlite3.Error:
            log.exception("Could not read settings; using defaults")
            return dict(DEFAULTS)
        merged = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
        with self._lock:
            self._cache = merged
        return dict(merged)

    def get(self, key: str) -> Any:
        return self.get_all()[key]

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    # ------------------------------------------------------------ validation
    def _validate(self, values: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, raw in values.items():
            if key == "school_name":
                clean[key] = clean_text(raw, key, "School name", max_len=60)
            elif key == "student_name":
                clean[key] = clean_text(raw, key, "Student name", max_len=40, required=False)
            elif key in ("default_day", "selected_day"):
                name = clean_text(raw, key, "Day", max_len=30)
                with self.db.read() as conn:
                    day = timetable_repo.get_day_by_name(conn, name)
                if not day:
                    raise ValidationError("Choose a day that exists in the timetable.", fields={key: "Unknown day"})
                clean[key] = day["name"]
            elif key == "timezone":
                name = clean_text(raw, key, "Timezone", max_len=64)
                if not is_valid_timezone(name):
                    raise ValidationError("That timezone is not recognised (example: Asia/Kolkata).",
                                          fields={key: "Unknown timezone"})
                clean[key] = name
            elif key in ("demo_enabled", "auto_start_session"):
                clean[key] = bool(raw) if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "on", "yes")
            elif key == "reader_type":
                if raw not in READER_TYPES:
                    raise ValidationError("Choose a valid reader type.", fields={key: "Invalid"})
                clean[key] = raw
            elif key == "reader_device":
                device = clean_text(raw, key, "Reader device", max_len=200, required=False)
                if device and not all(ch.isalnum() or ch in "_./:-" for ch in device):
                    raise ValidationError("Device paths may only contain letters, digits and _ . / : -",
                                          fields={key: "Invalid characters"})
                clean[key] = device
            elif key == "reader_baud":
                baud = to_int(raw, key, "Baud rate")
                if baud not in BAUD_RATES:
                    raise ValidationError("Choose a standard baud rate.", fields={key: "Invalid"})
                clean[key] = baud
            elif key == "debounce_seconds":
                clean[key] = to_int(raw, key, "Repeat-scan window", minimum=0, maximum=30)
            elif key == "admin_pin":
                clean[key] = str(raw)
            else:
                raise ValidationError(f"Unknown setting: {key}")
        return clean

    def update(self, values: dict[str, Any]) -> set[str]:
        """Validate and store settings; returns the keys whose value actually changed."""
        clean = self._validate(values)
        current = self.get_all()
        changed = {k for k, v in clean.items() if current.get(k) != v}
        if not changed:
            return set()
        with self.db.write() as conn:
            repo.set_many(conn, {k: clean[k] for k in changed})
        self.invalidate()
        self.bus.bump()
        for listener in self._listeners:
            try:
                listener(changed)
            except Exception:  # a listener must never break saving
                log.exception("Settings listener failed")
        return changed
