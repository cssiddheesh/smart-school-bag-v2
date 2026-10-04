"""JSON API used by the dashboard and Exhibition mode.

Envelope: ``{"success": bool, "message": str, "data": ...}``; errors add ``error:{code,message,...}``.
"""

from __future__ import annotations

from flask import Blueprint, request

from ..context import int_value, json_body, svc
from ..errors import AppError, ConflictError, NotFoundError, ok
from ..hardware import simulated
from ..security import admin_required
from ..utils import format_local

bp = Blueprint("api", __name__, url_prefix="/api")


class DemoDisabled(AppError):
    status = 403
    code = "demo_disabled"


def _require_demo() -> None:
    if not svc().settings.get("demo_enabled"):
        raise DemoDisabled("Demo mode is turned off. Enable it in Settings.")


def _with_state(message: str, extra: dict | None = None):
    return ok(message, {**(extra or {}), "state": svc().state.snapshot()})


@bp.get("/state")
def state():
    s = svc()
    rev = request.args.get("rev", type=int)
    if rev is not None and rev == s.bus.revision:
        return ok(data={"changed": False, "revision": rev})
    return ok(data={"changed": True, **s.state.snapshot()})


# ------------------------------------------------------------ sessions
@bp.post("/day")
def set_day():
    body = json_body()
    day = svc().sessions.set_day(int_value(body.get("day_id"), "day_id", "Day"), confirm=body.get("confirm") is True)
    return _with_state(f"Showing {day['name']}")


@bp.post("/session/start")
def start_session():
    session = svc().sessions.start(restart=False)
    return _with_state(f"Packing session started for {session['day_name']}", {"session_id": session["id"]})


@bp.post("/session/reset")
def reset_session():
    session = svc().sessions.reset()
    return _with_state("Session reset. Scan your books again.", {"session_id": session["id"]})


@bp.post("/session/complete")
def complete_session():
    s = svc()
    done = s.sessions.complete()
    return _with_state("Bag packed. Session complete.",
                       {"session_id": done["id"], "summary": _summary_view(s.sessions.summary(done["id"]))})


def _summary_view(summary: dict) -> dict:
    return {"id": summary["session"]["id"], "day_name": summary["session"]["day_name"],
            "packed_count": summary["packed_count"], "required_count": summary["required_count"],
            "duration_label": summary["duration_label"], "scan_count": summary["counts"]["total"],
            "duplicates": summary["counts"]["duplicate"], "extras": summary["extras"],
            "has_simulated": summary["has_simulated"]}


# ------------------------------------------------------------ demo / exhibition
@bp.post("/demo/scan")
def demo_scan():
    _require_demo()
    s = svc()
    body = json_body()
    if body.get("unknown") is True:
        uid = simulated.unknown_card_uid()
    else:
        book_id = int_value(body.get("book_id"), "book_id", "Book")
        book = next((b for b in s.books.list_active() if b["id"] == book_id), None)
        if not book:
            raise NotFoundError("Choose an enabled book to simulate.")
        uid = simulated.uid_for_book(book)
    result = s.scans.process(uid, "SIMULATION")
    return _with_state(result["message"], {"scan": result})


@bp.post("/demo/new-card")
def demo_new_card():
    """Hand a pretend, never-seen card to the 'scan to assign' capture (for demos without a reader)."""
    _require_demo()
    s = svc()
    if not s.scans.capture_active():
        raise ConflictError("Press “Scan card” on a book first.")
    s.scans.process(simulated.new_card_uid(), "SIMULATION")
    return ok("Simulated card presented", s.scans.capture_status())


# ------------------------------------------------------------ scan-to-assign capture (admin)
@bp.post("/capture/start")
@admin_required
def capture_start():
    svc().scans.start_capture()
    return ok("Waiting for a card…", svc().scans.capture_status())


@bp.post("/capture/cancel")
@admin_required
def capture_cancel():
    svc().scans.cancel_capture()
    return ok("Stopped waiting for a card.", {"active": False})


@bp.get("/capture")
@admin_required
def capture_status():
    return ok(data=svc().scans.capture_status())


# ------------------------------------------------------------ reader diagnostics
@bp.get("/reader")
def reader():
    s = svc()
    tz = s.settings.get("timezone")
    raw = [{**row, "time_label": format_local(row["time"], tz, "%H:%M:%S")} for row in s.reader.raw_log()]
    return ok(data={"status": s.reader.status(), "raw": raw})

