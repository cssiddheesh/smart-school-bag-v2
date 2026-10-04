"""Optional admin PIN (only active once a PIN has been set in Settings)."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import security
from ..context import svc
from ..utils import safe_next

bp = Blueprint("auth", __name__)


@bp.route("/unlock", methods=["GET", "POST"])
def unlock():
    target = safe_next(request.values.get("next"), url_for("pages.dashboard"))
    if not security.pin_enabled() or (security.admin_unlocked() and request.method == "GET"):
        return redirect(target)
    if request.method == "POST":
        client = request.remote_addr or "local"
        wait = security.lockout_remaining(client)
        if wait:
            flash(f"Too many attempts. Try again in {wait} seconds.", "error")
        elif security.verify_pin(request.form.get("pin", ""), svc().settings.get("admin_pin")):
            security.unlock()
            flash("Admin tools unlocked for 30 minutes.", "success")
            return redirect(target)
        else:
            security.record_failure(client)
            flash("That PIN is not correct.", "error")
    return render_template("unlock.html", next_url=target)


@bp.post("/lock")
def lock():
    security.lock()
    flash("Admin tools locked.", "success")
    return redirect(url_for("pages.dashboard"))
