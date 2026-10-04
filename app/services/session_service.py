"""Packing-session lifecycle: start, switch day, reset, complete, summarise."""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from ..bus import StateBus
from ..db import Database
from ..errors import ConflictError, NotFoundError, ValidationError
from ..repositories import scans as scans_repo
from ..repositories import sessions as repo
from ..repositories import timetable as timetable_repo
from ..utils import format_duration, seconds_between, utc_iso, utcnow
from .event_service import EventService
from .settings_service import SettingsService

log = logging.getLogger("ssb.sessions")


class SessionService:
    def __init__(self, db: Database, bus: StateBus, events: EventService, settings: SettingsService):
        self.db, self.bus, self.events, self.settings = db, bus, events, settings

    # ------------------------------------------------------------ day resolution
    def resolve_day(self, conn: sqlite3.Connection, day_id: Optional[int] = None) -> dict:
        if day_id is not None:
            day = timetable_repo.get_day(conn, day_id)
            if not day:
                raise NotFoundError("That day does not exist in the timetable.")
            return day
        cfg = self.settings.get_all()
        day = (timetable_repo.get_day_by_name(conn, cfg["selected_day"])
               or timetable_repo.get_day_by_name(conn, cfg["default_day"]))
        if not day:
            days = timetable_repo.list_days(conn)
            if not days:
                raise NotFoundError("The timetable has no days yet. Add one first.")
            day = days[0]
        return day

    # ------------------------------------------------------------ lifecycle
    def start_in_txn(self, conn: sqlite3.Connection, day_id: Optional[int] = None, *, restart: bool = False) -> dict:
        """Create a session inside an open write transaction (shared with auto-start on scan)."""
        day = self.resolve_day(conn, day_id)
        required = timetable_repo.required_books(conn, day["id"])
        if not required:
            raise ValidationError(f"{day['name']} has no books in the timetable. Add periods first.")
        active = repo.get_active(conn)
        if active:
            if not restart:
                raise ConflictError("A packing session is already in progress.", code="session_active")
            repo.set_status(conn, active["id"], "abandoned", utc_iso())
        session_id = repo.create(conn, day["id"], required, utc_iso())
        return {"id": session_id, "day_id": day["id"], "day_name": day["name"]}

    def start(self, day_id: Optional[int] = None, *, restart: bool = False) -> dict:
        with self.db.write() as conn:
            session = self.start_in_txn(conn, day_id, restart=restart)
        self._after_start(session)
        return session

    def _after_start(self, session: dict) -> None:
        self.settings.update({"selected_day": session["day_name"]})
        self.bus.bump()
        self.events.log("info", "session", f"Session #{session['id']} started for {session['day_name']}")

    def reset(self) -> dict:
        """Abandon the active session (kept in history) and begin a clean one for the same day."""
        with self.db.read() as conn:
            active = repo.get_active(conn)
        return self.start(active["day_id"] if active else None, restart=True)

    def set_day(self, day_id: int, *, confirm: bool = False) -> dict:
        with self.db.write() as conn:
            day = self.resolve_day(conn, day_id)
            active = repo.get_active(conn)
            ended = None
            if active and active["day_id"] != day["id"]:
                if not confirm:
                    count = scans_repo.session_counts(conn, active["id"])["total"]
                    raise ConflictError(
                        f"Switching to {day['name']} ends the current {active['day_name']} session.",
                        code="session_in_progress", details={"scan_count": count, "current_day": active["day_name"]})
                repo.set_status(conn, active["id"], "abandoned", utc_iso())
                ended = active["id"]
        self.settings.update({"selected_day": day["name"]})
        self.bus.bump()
        if ended:
            self.events.log("info", "session", f"Session #{ended} abandoned (day changed to {day['name']})")
        return day

    def complete(self) -> dict:
        with self.db.write() as conn:
            active = repo.get_active(conn)
            if not active:
                raise ConflictError("There is no active packing session.", code="no_session")
            required = repo.required_books(conn, active["id"])
            accepted = {o["book_id"] for o in scans_repo.book_outcomes(conn, active["id"]) if o["outcome"] == "accepted"}
            missing = [r["name"] for r in required if r["book_id"] not in accepted]
            if missing:
                raise ConflictError(f"Still missing: {', '.join(missing)}.", code="not_ready",
                                    details={"missing": missing})
            repo.set_status(conn, active["id"], "completed", utc_iso())
        self.bus.bump()
        self.events.log("info", "session", f"Session #{active['id']} completed ({active['day_name']})")
        return {"id": active["id"], "day_name": active["day_name"]}

    # ------------------------------------------------------------ read models
    def summary(self, session_id: int) -> dict:
        with self.db.read() as conn:
            session = repo.get(conn, session_id)
            if not session:
                raise NotFoundError("That packing session does not exist.")
            required = repo.required_books(conn, session_id)
            outcomes = scans_repo.book_outcomes(conn, session_id)
            counts = scans_repo.session_counts(conn, session_id)
            scans = scans_repo.for_session(conn, session_id)
        accepted = {o["book_id"] for o in outcomes if o["outcome"] == "accepted"}
        rows = [{"book_id": r["book_id"], "name": r["name"], "present": r["book_id"] in accepted} for r in required]
        end = session["completed_at"] or utc_iso(utcnow())
        duration = seconds_between(session["started_at"], end)
        packed = sum(1 for r in rows if r["present"])
        return {
            "session": session,
            "required": rows,
            "missing": [r["name"] for r in rows if not r["present"]],
            "extras": [o["book_name"] for o in outcomes if o["outcome"] == "not_required"],
            "counts": counts,
            "packed_count": packed,
            "required_count": len(rows),
            "percentage": round(packed * 100 / len(rows)) if rows else 100,
            "ready": packed == len(rows),
            "duration_seconds": duration,
            "duration_label": format_duration(duration),
            "has_simulated": counts["simulated"] > 0,
            "has_real": counts["real"] > 0,
            "scans": scans,
        }
