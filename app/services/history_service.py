"""Scan history, session history and the (confirmed) clear-history action."""

from __future__ import annotations

from typing import Optional

from ..bus import StateBus
from ..db import Database
from ..repositories import scans as scans_repo
from ..repositories import sessions as sessions_repo
from ..utils import format_duration, format_local, seconds_between, utc_iso, utcnow
from .backup_service import BackupService
from .event_service import EventService
from .settings_service import SettingsService

PER_PAGE = 25
SOURCES = ("RFID", "SIMULATION")
OUTCOMES = ("accepted", "duplicate", "not_required", "unknown_card", "disabled", "no_session", "legacy")
SESSION_STATUSES = ("active", "completed", "abandoned")


def _page(total: int, page: int) -> tuple[int, int]:
    pages = max(1, -(-total // PER_PAGE))
    return min(max(1, page), pages), pages


class HistoryService:
    def __init__(self, db: Database, bus: StateBus, events: EventService,
                 settings: SettingsService, backup: BackupService):
        self.db, self.bus, self.events, self.settings, self.backup = db, bus, events, settings, backup

    def scans(self, *, query: str = "", day_id: Optional[int] = None, session_id: Optional[int] = None,
              source: Optional[str] = None, outcome: Optional[str] = None, page: int = 1) -> dict:
        tz = self.settings.get("timezone")
        filters = dict(query=query, day_id=day_id, session_id=session_id,
                       source=source if source in SOURCES else None,
                       outcome=outcome if outcome in OUTCOMES else None)
        with self.db.read() as conn:
            _, total = scans_repo.search(conn, **filters, limit=1, offset=0)
            page, pages = _page(total, page)
            rows, _ = scans_repo.search(conn, **filters, limit=PER_PAGE, offset=(page - 1) * PER_PAGE)
        for row in rows:
            row["time_label"] = format_local(row["scanned_at"], tz)
        return {"rows": rows, "total": total, "page": page, "pages": pages}

    def sessions(self, *, day_id: Optional[int] = None, status: Optional[str] = None, page: int = 1) -> dict:
        tz = self.settings.get("timezone")
        status = status if status in SESSION_STATUSES else None
        with self.db.read() as conn:
            _, total = sessions_repo.search(conn, day_id=day_id, status=status, limit=1, offset=0)
            page, pages = _page(total, page)
            rows, _ = sessions_repo.search(conn, day_id=day_id, status=status, limit=PER_PAGE,
                                           offset=(page - 1) * PER_PAGE)
        now = utc_iso(utcnow())
        for row in rows:
            row["started_label"] = format_local(row["started_at"], tz)
            row["duration_label"] = format_duration(seconds_between(row["started_at"], row["completed_at"] or now))
        return {"rows": rows, "total": total, "page": page, "pages": pages}

    def totals(self) -> dict:
        with self.db.read() as conn:
            return scans_repo.totals(conn)

    def clear(self) -> int:
        """Delete scans and finished sessions after taking a safety backup. Active session stays."""
        self.backup.create("pre-clear")
        with self.db.write() as conn:
            active = sessions_repo.get_active(conn)
            removed = scans_repo.clear(conn, active["id"] if active else None)
        self.bus.bump()
        self.events.log("warning", "history", f"History cleared ({removed} scans removed)")
        return removed
