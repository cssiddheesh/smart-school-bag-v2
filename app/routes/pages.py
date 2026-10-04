"""Read-only pages: dashboard, exhibition, history, session summary, health."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..context import svc
from ..errors import fail, ok
from ..services.history_service import OUTCOMES, SESSION_STATUSES, SOURCES

bp = Blueprint("pages", __name__)

OUTCOME_LABELS = {
    "accepted": "Detected", "duplicate": "Duplicate", "not_required": "Not required",
    "unknown_card": "Unknown card", "disabled": "Disabled book", "no_session": "No session",
    "legacy": "Earlier version",
}


def _int_arg(name: str):
    value = request.args.get(name, type=int)
    return value if value and value > 0 else None


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", state=svc().state.snapshot())


@bp.get("/dashboard")
def dashboard_alias():
    return redirect(url_for("pages.dashboard"), code=301)


@bp.get("/exhibition")
def exhibition():
    s = svc()
    if not s.settings.get("demo_enabled"):
        flash("Turn on demo mode in Settings to use Exhibition mode.", "warning")
        return redirect(url_for("pages.dashboard"))
    return render_template("exhibition.html", state=s.state.snapshot(), books=[{"id": b["id"], "name": b["name"]} for b in s.books.list_active()])


@bp.get("/history")
def history():
    s = svc()
    view = "sessions" if request.args.get("view") == "sessions" else "scans"
    page = request.args.get("page", 1, type=int) or 1
    query = (request.args.get("q") or "").strip()[:60]
    day_id, session_id = _int_arg("day"), _int_arg("session")
    source, outcome = request.args.get("source", ""), request.args.get("outcome", "")
    status = request.args.get("status", "")
    if view == "sessions":
        data = s.history.sessions(day_id=day_id, status=status or None, page=page)
    else:
        data = s.history.scans(query=query, day_id=day_id, session_id=session_id,
                               source=source or None, outcome=outcome or None, page=page)
    pager_params = {k: v for k, v in {"view": view, "q": query, "day": day_id, "source": source,
                                       "outcome": outcome, "session": session_id, "status": status}.items() if v}
    return render_template(
        "history.html", view=view, pager_params=pager_params, data=data, totals=s.history.totals(), days=s.timetable.days(),
        filters={"q": query, "day": day_id, "session": session_id, "source": source, "outcome": outcome,
                 "status": status},
        sources=SOURCES, outcomes=[(o, OUTCOME_LABELS[o]) for o in OUTCOMES], statuses=SESSION_STATUSES,
        outcome_labels=OUTCOME_LABELS)


@bp.get("/sessions/<int:session_id>")
def session_detail(session_id: int):
    s = svc()
    return render_template("session.html", summary=s.sessions.summary(session_id),
                           tz=s.settings.get("timezone"), outcome_labels=OUTCOME_LABELS)


@bp.get("/healthz")
def healthz():
    s = svc()
    try:
        with s.db.read() as conn:
            conn.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return fail("database_unavailable", "Database unavailable", 503)
    return ok("ok", {"status": "ok", "version": current_app.config["APP_VERSION"],
                     "reader": s.reader.status()["state"], "revision": s.bus.revision})
