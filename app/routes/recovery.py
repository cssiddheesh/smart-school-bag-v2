"""Recovery mode: shown when the database can't be opened (corrupt or unreadable)."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from ..context import svc
from ..errors import AppError

bp = Blueprint("recovery", __name__)


def _recovered() -> None:
    current_app.config["DB_ERROR"] = None
    svc().settings.invalidate()
    if current_app.config.get("START_READER"):
        svc().reader.start()


@bp.get("/recovery")
def page():
    error = current_app.config.get("DB_ERROR")
    if not error:
        return redirect(url_for("pages.dashboard"))
    return render_template("recovery.html", error=error, backups=svc().backup.list())


def _attempt(action):
    try:
        action()
    except AppError as error:
        flash(error.message, "error")
        return redirect(url_for("recovery.page"))
    _recovered()
    flash("The database was recovered.", "success")
    return redirect(url_for("pages.dashboard"))


@bp.post("/recovery/restore")
def restore_named():
    name = request.form.get("name", "")
    return _attempt(lambda: svc().backup.restore_named(name, database_failed=True))


@bp.post("/recovery/upload")
def restore_upload():
    return _attempt(lambda: svc().backup.restore_upload(request.files.get("backup_file"), database_failed=True))


@bp.post("/recovery/fresh")
def fresh():
    error = current_app.config.get("DB_ERROR")
    if not (error and error.get("corrupt")):
        flash("A new database can only be started when the old one is damaged.", "error")
        return redirect(url_for("recovery.page"))
    return _attempt(lambda: svc().backup.start_fresh())

