"""Service container: wires repositories, services and the reader together."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..bus import StateBus
from ..db import Database
from ..hardware.manager import ReaderManager
from .backup_service import BackupService
from .book_service import BookService
from .event_service import EventService
from .history_service import HistoryService
from .scan_service import ScanService
from .session_service import SessionService
from .settings_service import READER_KEYS, SettingsService
from .state_service import StateService
from .system_service import SystemService
from .timetable_service import TimetableService


@dataclass
class Services:
    db: Database
    bus: StateBus
    events: EventService
    settings: SettingsService
    books: BookService
    timetable: TimetableService
    sessions: SessionService
    scans: ScanService
    state: StateService
    backup: BackupService
    reader: ReaderManager
    history: HistoryService
    system: SystemService


def build_services(db: Database, backup_dir: Path, version: str = "", reader_factory=None) -> Services:
    bus = StateBus()
    events = EventService(db)
    settings = SettingsService(db, bus)
    books = BookService(db, bus, events)
    timetable = TimetableService(db, bus, events)
    sessions = SessionService(db, bus, events, settings)
    scans = ScanService(db, bus, events, settings, sessions)

    def on_status(status: dict[str, Any]) -> None:
        bus.bump()
        level = "info" if status["state"] in ("connected", "disabled") else "warning"
        events.log(level, "reader", f"RFID reader {status['state']}: {status['message']}")

    kwargs = {"factory": reader_factory} if reader_factory else {}
    reader = ReaderManager(settings.get_all, lambda raw: scans.process(raw, "RFID"), on_status, **kwargs)
    settings.add_listener(lambda changed: reader.reconfigure() if changed & READER_KEYS else None)
    backup = BackupService(db, backup_dir, bus, events, settings)
    return Services(db, bus, events, settings, books, timetable, sessions, scans,
                    StateService(db, bus, settings, reader), backup, reader,
                    HistoryService(db, bus, events, settings, backup), SystemService(db, version))
