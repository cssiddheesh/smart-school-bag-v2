"""Management pages: books, timetable, settings, backups, clear history.

All handlers are thin: validate the request shape, call a service, flash, redirect.
"""

from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request, send_from_directory, url_for)

from .. import security
from ..context import form_action, int_value, return_target, svc
from ..errors import ValidationError
from ..security import admin_required
from ..utils import format_local, utc_iso
from ..services.settings_service import BAUD_RATES, READER_TYPES

bp = Blueprint("admin", __name__)


def _checkbox(name: str) -> bool:
    return name in request.form


# ================================================================ books
@bp.get("/books")
@admin_required
def books():
    s = svc()
    state = s.state.snapshot()
    names = {item["name"] for item in state["checklist"]}
    return render_template("books.html", books=s.books.list_with_status(names), day=state["day"],
                           demo_enabled=state["demo_enabled"])


@bp.post("/books/add")
@admin_required
@form_action("admin.books")
def book_add():
    book = svc().books.add(request.form.get("name", ""))
    flash(f"{book['name']} added. Assign its card next.", "success")
    return redirect(return_target("admin.books"))


@bp.post("/books/<int:book_id>/rename")
@admin_required
@form_action("admin.books")
def book_rename(book_id: int):
    svc().books.rename(book_id, request.form.get("name", ""))
    flash("Book renamed.", "success")
    return redirect(return_target("admin.books"))


@bp.post("/books/<int:book_id>/uid")
@admin_required
@form_action("admin.books")
def book_assign_uid(book_id: int):
    replaced = svc().books.assign_uid(book_id, request.form.get("rfid_uid", ""))
    flash("Card replaced." if replaced else "Card assigned.", "success")
    return redirect(return_target("admin.books"))


@bp.post("/books/<int:book_id>/uid/remove")
@admin_required
@form_action("admin.books")
def book_remove_uid(book_id: int):
    svc().books.remove_uid(book_id)
    flash("Card unassigned.", "success")
    return redirect(return_target("admin.books"))


@bp.post("/books/<int:book_id>/active")
@admin_required
@form_action("admin.books")
def book_set_active(book_id: int):
    active = request.form.get("active") == "1"
    svc().books.set_active(book_id, active)
    flash("Book enabled." if active else "Book disabled. It no longer counts as required.", "success")
    return redirect(return_target("admin.books"))


@bp.post("/books/<int:book_id>/delete")
@admin_required
@form_action("admin.books")
def book_delete(book_id: int):
    svc().books.delete(book_id)
    flash("Book deleted.", "success")
    return redirect(return_target("admin.books"))


# ================================================================ timetable
@bp.get("/timetable")
@admin_required
def timetable():
    s = svc()
    days = s.timetable.days()
    if not days:
        return render_template("timetable.html", days=[], view=None, books=s.books.list_active())
    wanted = request.args.get("day", type=int)
    current = s.state.snapshot()["day"]
    day_id = wanted if any(d["id"] == wanted for d in days) else (current["id"] if current else days[0]["id"])
    return render_template("timetable.html", days=days, view=s.timetable.day_view(day_id), books=s.books.list_active())


def _day_redirect(day_id: int | None = None):
    if day_id:
        return redirect(url_for("admin.timetable", day=day_id))
    return redirect(return_target("admin.timetable"))


@bp.post("/timetable/days/add")
@admin_required
@form_action("admin.timetable")
def day_add():
    day_id = svc().timetable.add_day(request.form.get("name", ""))
    flash("Day added. Add its periods below.", "success")
    return _day_redirect(day_id)


@bp.post("/timetable/days/<int:day_id>/rename")
@admin_required
@form_action("admin.timetable")
def day_rename(day_id: int):
    svc().timetable.rename_day(day_id, request.form.get("name", ""))
    flash("Day renamed.", "success")
    return _day_redirect(day_id)


@bp.post("/timetable/days/<int:day_id>/delete")
@admin_required
@form_action("admin.timetable")
def day_delete(day_id: int):
    svc().timetable.delete_day(day_id)
    flash("Day deleted.", "success")
    return redirect(url_for("admin.timetable"))


@bp.post("/timetable/days/<int:day_id>/move")
@admin_required
@form_action("admin.timetable")
def day_move(day_id: int):
    svc().timetable.move_day(day_id, request.form.get("direction", ""))
    return _day_redirect(request.form.get("current_day", type=int) or day_id)


@bp.post("/timetable/days/<int:day_id>/entries/add")
@admin_required
@form_action("admin.timetable")
def entry_add(day_id: int):
    svc().timetable.add_entry(day_id, int_value(request.form.get("book_id"), "book_id", "Book"))
    flash("Period added.", "success")
    return _day_redirect(day_id)


@bp.post("/timetable/entries/<int:entry_id>/book")
@admin_required
@form_action("admin.timetable")
def entry_set_book(entry_id: int):
    svc().timetable.set_entry_book(entry_id, int_value(request.form.get("book_id"), "book_id", "Book"))
    flash("Period updated.", "success")
    return redirect(return_target("admin.timetable"))


@bp.post("/timetable/entries/<int:entry_id>/remove")
@admin_required
@form_action("admin.timetable")
def entry_remove(entry_id: int):
    svc().timetable.remove_entry(entry_id)
    flash("Period removed.", "success")
    return redirect(return_target("admin.timetable"))


@bp.post("/timetable/entries/<int:entry_id>/move")
@admin_required
@form_action("admin.timetable")
def entry_move(entry_id: int):
    svc().timetable.move_entry(entry_id, request.form.get("direction", ""))
    return redirect(return_target("admin.timetable"))


# ================================================================ settings
@bp.get("/settings")
@admin_required
def settings():
    s = svc()
    cfg = s.settings.get_all()
    tz = cfg["timezone"]
    events = s.events.recent(15)
    for event in events:
        event["time_label"] = format_local(event["ts"], tz, "%d %b, %H:%M:%S")
    return render_template(
        "settings.html", cfg=cfg, days=s.timetable.days(), reader_status=s.reader.status(),
        raw_log=s.reader.raw_log(), backups=s.backup.list(), events=events, system=s.system.info(),
        now_label=format_local(utc_iso(), tz, "%H:%M, %d %b"), reader_types=READER_TYPES, baud_rates=BAUD_RATES)


@bp.post("/settings/general")
@admin_required
@form_action("admin.settings")
def settings_general():
    svc().settings.update({
        "school_name": request.form.get("school_name", ""),
        "student_name": request.form.get("student_name", ""),
        "default_day": request.form.get("default_day", ""),
        "timezone": request.form.get("timezone", ""),
        "auto_start_session": _checkbox("auto_start_session"),
        "debounce_seconds": request.form.get("debounce_seconds", ""),
    })
    flash("Settings saved.", "success")
    return redirect(url_for("admin.settings") + "#general")


@bp.post("/settings/reader")
@admin_required
@form_action("admin.settings")
def settings_reader():
    values = {"demo_enabled": _checkbox("demo_enabled"),
              "reader_type": request.form.get("reader_type", "none"),
              "reader_device": request.form.get("reader_device", ""),
              "reader_baud": request.form.get("reader_baud", "9600")}
    svc().settings.update(values)
    flash("Reader and demo settings saved.", "success")
    return redirect(url_for("admin.settings") + "#reader")


@bp.post("/settings/pin")
@admin_required
@form_action("admin.settings")
def settings_pin():
    s = svc()
    if request.form.get("action") == "remove":
        s.settings.update({"admin_pin": ""})
        security.lock()
        flash("Admin PIN removed. Admin pages are open to everyone on this network.", "success")
    else:
        pin, confirm = request.form.get("pin", ""), request.form.get("pin_confirm", "")
        if not (4 <= len(pin) <= 12 and pin.isdigit()):
            raise ValidationError("The PIN must be 4-12 digits.", fields={"pin": "Invalid"})
        if pin != confirm:
            raise ValidationError("The two PINs do not match.", fields={"pin_confirm": "Mismatch"})
        s.settings.update({"admin_pin": security.hash_pin(pin)})
        security.unlock()
        flash("Admin PIN saved. Admin pages now ask for it.", "success")
    return redirect(url_for("admin.settings") + "#security")


# ================================================================ backups
@bp.post("/backups/create")
@admin_required
@form_action("admin.settings")
def backup_create():
    path = svc().backup.create("manual")
    flash(f"Backup created: {path.name}", "success")
    return redirect(url_for("admin.settings") + "#backup")


@bp.get("/backups/<name>/download")
@admin_required
def backup_download(name: str):
    path = svc().backup.path_for(name)
    return send_from_directory(path.parent, path.name, as_attachment=True, mimetype="application/vnd.sqlite3")


@bp.post("/backups/<name>/restore")
@admin_required
@form_action("admin.settings")
def backup_restore(name: str):
    svc().backup.restore_named(name)
    flash("Backup restored. A safety copy of the previous data was kept.", "success")
    return redirect(url_for("admin.settings") + "#backup")


@bp.post("/backups/<name>/delete")
@admin_required
@form_action("admin.settings")
def backup_delete(name: str):
    svc().backup.delete(name)
    flash("Backup deleted.", "success")
    return redirect(url_for("admin.settings") + "#backup")


@bp.post("/backups/upload")
@admin_required
@form_action("admin.settings")
def backup_upload():
    svc().backup.restore_upload(request.files.get("backup_file"))
    flash("Backup restored. A safety copy of the previous data was kept.", "success")
    return redirect(url_for("admin.settings") + "#backup")


# ================================================================ history
@bp.post("/history/clear")
@admin_required
@form_action("pages.history")
def history_clear():
    removed = svc().history.clear()
    flash(f"History cleared ({removed} scans removed). A backup was saved first.", "success")
    return redirect(url_for("pages.history"))

