"""Builds the single JSON snapshot the dashboard renders from."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..bus import StateBus
from ..db import Database
from ..repositories import scans as scans_repo
from ..repositories import sessions as sessions_repo
from ..repositories import timetable as timetable_repo
from ..utils import format_local, utc_iso, utcnow
from .bag_status import calculate_bag_status
from .scan_service import describe
from .settings_service import SettingsService

STATUS_LABELS = {"idle": "NOT STARTED", "not_ready": "BAG NOT READY", "ready": "BAG READY", "empty": "NO BOOKS TODAY"}
IDLE_SCAN_WINDOW = timedelta(minutes=2)


class StateService:
    def __init__(self, db: Database, bus: StateBus, settings: SettingsService, reader):
        self.db, self.bus, self.settings, self.reader = db, bus, settings, reader

    def snapshot(self) -> dict[str, Any]:
        cfg = self.settings.get_all()
        tz = cfg["timezone"]
        with self.db.read() as conn:
            revision = self.bus.revision
            days = timetable_repo.list_days(conn)
            active = sessions_repo.get_active(conn)
            if active:
                day = next((d for d in days if d["id"] == active["day_id"]), None)
                required = sessions_repo.required_books(conn, active["id"])
                counted = scans_repo.book_outcomes(conn, active["id"])
                last_scan = scans_repo.last_in_session(conn, active["id"])
                sources = scans_repo.session_counts(conn, active["id"])
            else:
                day = (timetable_repo.get_day_by_name(conn, cfg["selected_day"])
                       or timetable_repo.get_day_by_name(conn, cfg["default_day"]) or (days[0] if days else None))
                required = timetable_repo.required_books(conn, day["id"]) if day else []
                counted = []
                last_scan = scans_repo.last_since(conn, utc_iso(utcnow() - IDLE_SCAN_WINDOW))
                sources = None
            last_finished = None if active else sessions_repo.last_finished(conn)

        accepted_ids = {o["book_id"] for o in counted if o["outcome"] == "accepted"}
        detected = [o["book_name"] for o in counted]
        bag = calculate_bag_status([r["name"] for r in required], detected)
        if not required:
            phase = "empty"
        elif not active:
            phase = "idle"
        else:
            phase = "ready" if bag["ready"] else "not_ready"

        checklist = [{"book_id": r["book_id"], "name": r["name"], "present": r["book_id"] in accepted_ids}
                     for r in required]
        scan_view = None
        if last_scan:
            message, level = describe(last_scan["outcome"], last_scan["book_name"])
            scan_view = {"id": last_scan["id"], "outcome": last_scan["outcome"], "message": message, "level": level,
                         "source": last_scan["source"], "book_name": last_scan["book_name"],
                         "time_label": format_local(last_scan["scanned_at"], tz, "%H:%M:%S")}
        finished_view = None
        if last_finished:
            finished_view = {"id": last_finished["id"], "day_name": last_finished["day_name"],
                             "status": last_finished["status"],
                             "time_label": format_local(last_finished["completed_at"], tz, "%d %b, %H:%M")}
        return {
            "revision": revision,
            "phase": phase,
            "status": STATUS_LABELS[phase],
            "ready": phase == "ready",
            "day": day,
            "days": days,
            "session": ({"id": active["id"], "day_name": active["day_name"],
                         "started_label": format_local(active["started_at"], tz, "%H:%M"),
                         "has_simulated": bool(sources and sources["simulated"]),
                         "has_real": bool(sources and sources["real"])} if active else None),
            "checklist": checklist,
            "missing": bag["missing_books"] if active else [],
            "extras": bag["extra_books"],
            "packed_count": bag["packed_count"],
            "required_count": bag["required_count"],
            "percentage": bag["percentage"] if active else 0,
            "last_scan": scan_view,
            "last_session": finished_view,
            "reader": self.reader.status(),
            "demo_enabled": cfg["demo_enabled"],
            "school_name": cfg["school_name"],
            "student_name": cfg["student_name"],
        }
