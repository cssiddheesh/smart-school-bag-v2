"""Smart School Bag - Python + RFID packing assistant (application factory)."""

from __future__ import annotations

import atexit
import logging
from typing import Any

from flask import Flask, render_template, request, url_for

from .config import load_config, load_secret_key
from .db import Database, initialize
from .errors import DatabaseStartupError, fail, register_error_handlers, wants_json
from .security import admin_unlocked, csrf_token, init_security, pin_enabled
from .services import build_services
from .utils import format_duration, format_local
from .logging_setup import setup_logging

log = logging.getLogger("ssb")

_DB_EXEMPT = {"recovery.page", "recovery.restore_named", "recovery.restore_upload", "recovery.fresh",
              "pages.healthz", "static"}


def create_app(overrides: dict[str, Any] | None = None) -> Flask:
    config = load_config(overrides)
    app = Flask(__name__)
    app.config.from_mapping(config)
    app.json.sort_keys = False
    app.config["LARGE_UPLOAD_ENDPOINTS"] = ("admin.backup_upload", "recovery.restore_upload")

    setup_logging(app.config["LOG_DIR"], app.config["LOG_LEVEL"])
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.config["DATA_DIR"])
    log.info("Starting Smart School Bag %s", app.config["APP_VERSION"])

    db = Database(app.config["DATABASE_PATH"])
    app.config["DB_ERROR"] = None
    try:
        initialize(db, app.config["BACKUP_DIR"])
    except DatabaseStartupError as error:
        log.error("Database problem at startup: %s", error.reason)
        app.config["DB_ERROR"] = {"reason": error.reason, "corrupt": error.corrupt}

    services = build_services(db, app.config["BACKUP_DIR"], app.config["APP_VERSION"])
    app.extensions["ssb"] = services

    init_security(app)
    register_error_handlers(app)

    @app.before_request
    def _database_guard():
        if app.config.get("DB_ERROR") and request.endpoint not in _DB_EXEMPT:
            if wants_json():
                return fail("database_unavailable", "The database needs attention.", 503)
            return render_template("recovery.html", error=app.config["DB_ERROR"],
                                   backups=services.backup.list()), 503

    from .routes import admin, api, auth, pages, recovery
    for module in (pages, api, admin, auth, recovery):
        app.register_blueprint(module.bp)

    @app.template_filter("localtime")
    def _localtime(value, fmt="%d %b %Y, %H:%M"):
        return format_local(value, services.settings.get("timezone"), fmt)

    app.jinja_env.filters["duration"] = format_duration

    @app.context_processor
    def _inject():
        cfg = services.settings.get_all()
        return {
            "cfg": cfg, "reader": services.reader.status(), "demo_enabled": cfg["demo_enabled"],
            "pin_enabled": pin_enabled(), "admin_unlocked": admin_unlocked(), "csrf_token": csrf_token,
            "app_version": app.config["APP_VERSION"],
            "static_url": lambda path: url_for("static", filename=path, v=app.config["APP_VERSION"]),
        }

    if app.config["START_READER"] and not app.config["DB_ERROR"]:
        services.reader.start()
        atexit.register(services.reader.stop)
    return app
