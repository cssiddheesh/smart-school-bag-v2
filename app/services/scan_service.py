"""THE scan pipeline. Real reader scans and simulated scans both end up in ``process``.

    receive UID -> normalise -> (debounce) -> (capture) -> resolve book -> find/start
    session -> classify -> record + update in ONE transaction -> bump revision
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Optional

from ..bus import StateBus
from ..db import Database
from ..errors import AppError
from ..repositories import books as books_repo
from ..repositories import scans as repo
from ..repositories import sessions as sessions_repo
from ..utils import UID_MAX_LEN, UID_MIN_LEN, mask_uid, normalize_uid, utc_iso
from .event_service import EventService
from .session_service import SessionService
from .settings_service import SettingsService

log = logging.getLogger("ssb.scan")

CAPTURE_SECONDS = 30
_SIM_PATTERN = re.compile(r"SIM(\d+)")


def describe(outcome: Optional[str], book_name: Optional[str]) -> tuple[str, str]:
    """Human message and level (success/warning/info) for a stored outcome."""
    name = book_name or "Book"
    table = {
        "accepted": (f"{name} detected", "success"),
        "duplicate": (f"{name} already scanned", "warning"),
        "not_required": (f"{name} is not required today", "warning"),
        "unknown_card": ("Unknown RFID card", "warning"),
        "disabled": (f"{name} is disabled and can't be packed", "warning"),
        "no_session": ("Start a packing session first", "warning"),
    }
    if outcome in table:
        return table[outcome]
    return (f"{name} scanned" if book_name else "Card scanned", "info")  # legacy rows


class ScanService:
    def __init__(self, db: Database, bus: StateBus, events: EventService,
                 settings: SettingsService, sessions: SessionService):
        self.db, self.bus, self.events = db, bus, events
        self.settings, self.sessions = settings, sessions
        self._lock = threading.Lock()
        self._recent: dict[str, float] = {}
        self._capture: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------ capture ("scan to assign")
    def start_capture(self, seconds: int = CAPTURE_SECONDS) -> None:
        with self._lock:
            self._capture = {"expires": time.monotonic() + seconds, "uid": None}
        log.info("Card capture started (%ds)", seconds)

    def cancel_capture(self) -> None:
        with self._lock:
            self._capture = None

    def capture_status(self) -> dict:
        """Poll the capture; once a UID was delivered it is returned exactly once."""
        with self._lock:
            cap = self._capture
            if cap is None:
                return {"active": False, "uid": None, "seconds_left": 0}
            left = max(0, int(cap["expires"] - time.monotonic()))
            if cap["uid"]:
                self._capture = None
                return {"active": False, "uid": cap["uid"], "seconds_left": left}
            if left == 0:
                self._capture = None
                return {"active": False, "uid": None, "seconds_left": 0}
            return {"active": True, "uid": None, "seconds_left": left}

    def capture_active(self) -> bool:
        with self._lock:
            return self._capture is not None and self._capture["uid"] is None and time.monotonic() < self._capture["expires"]

    def _try_capture(self, uid: str) -> bool:
        with self._lock:
            cap = self._capture
            if cap is None or time.monotonic() > cap["expires"]:
                return False
            if cap["uid"] is None:
                cap["uid"] = uid
            return True

    # ------------------------------------------------------------ debounce
    def _is_repeat(self, uid: str) -> bool:
        window = self.settings.get("debounce_seconds")
        now = time.monotonic()
        with self._lock:
            last = self._recent.get(uid)
            self._recent[uid] = now  # a card held on the reader keeps being suppressed
            for key in [k for k, t in self._recent.items() if now - t > 120]:
                del self._recent[key]
        return bool(window) and last is not None and (now - last) < window

    # ------------------------------------------------------------ pipeline
    @staticmethod
    def _result(outcome: str, message: str, level: str, *, source: str, book: Optional[dict] = None,
                session_id: Optional[int] = None, ready: bool = False, became_ready: bool = False,
                recorded: bool = True) -> dict:
        return {"outcome": outcome, "message": message, "level": level, "source": source,
                "book": {"id": book["id"], "name": book["name"]} if book else None,
                "session_id": session_id, "ready": ready, "became_ready": became_ready, "recorded": recorded}

    def process(self, raw_uid: object, source: str = "RFID") -> dict:
        source = "SIMULATION" if str(source).upper() == "SIMULATION" else "RFID"
        uid = normalize_uid(raw_uid)
        if not UID_MIN_LEN <= len(uid) <= UID_MAX_LEN:
            log.warning("Ignored malformed read (%d characters, source=%s)", len(uid), source)
            return self._result("ignored", "Ignored an unreadable card read", "warning", source=source, recorded=False)
        if source == "RFID" and self._is_repeat(uid):
            return self._result("debounced", "Repeated read ignored", "info", source=source, recorded=False)
        if self._try_capture(uid):
            log.info("Card %s captured for assignment", mask_uid(uid))
            return self._result("captured", "Card captured", "info", source=source, recorded=False)

        with self.db.write() as conn:
            book = books_repo.get_by_uid(conn, uid)
            if book is None and source == "SIMULATION":
                match = _SIM_PATTERN.fullmatch(uid)
                book = books_repo.get(conn, int(match.group(1))) if match else None
            session = sessions_repo.get_active(conn)
            now = utc_iso()
            session_id = session["id"] if session else None
            ready = became_ready = False

            if book is None:
                outcome = "unknown_card"
            elif not book["is_active"]:
                outcome = "disabled"
            else:
                if session is None and self.settings.get("auto_start_session"):
                    try:
                        session = self.sessions.start_in_txn(conn)
                        session_id = session["id"]
                        session["_new"] = True
                    except AppError as error:
                        log.info("Auto-start skipped: %s", error.message)
                if session is None:
                    outcome = "no_session"
                else:
                    required_ids = {r["book_id"] for r in sessions_repo.required_books(conn, session_id)}
                    if book["id"] in required_ids:
                        outcome = "duplicate" if repo.has_counted(conn, session_id, book["id"], "accepted") else "accepted"
                    else:
                        outcome = "duplicate" if repo.has_counted(conn, session_id, book["id"], "not_required") else "not_required"

            repo.insert(conn, uid=uid, book_name=book["name"] if book else None,
                        book_id=book["id"] if book else None, source=source,
                        session_id=session_id if outcome != "no_session" else None, outcome=outcome, now=now)
            if session_id and outcome in ("accepted", "duplicate", "not_required"):
                required_ids = {r["book_id"] for r in sessions_repo.required_books(conn, session_id)}
                accepted = {o["book_id"] for o in repo.book_outcomes(conn, session_id) if o["outcome"] == "accepted"}
                ready = required_ids <= accepted
                became_ready = ready and outcome == "accepted"
            started = session if (session and session.get("_new")) else None

        if started:
            self.events.log("info", "session", f"Session #{started['id']} auto-started for {started['day_name']}")
        message, level = describe(outcome, book["name"] if book else None)
        log.info("Scan source=%s uid=%s outcome=%s book=%s", source, mask_uid(uid), outcome,
                 book["name"] if book else "-")
        self.bus.bump()
        return self._result(outcome, message, level, source=source, book=book,
                            session_id=session_id, ready=ready, became_ready=became_ready)
