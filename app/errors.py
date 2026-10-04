"""Domain exceptions and the single place where errors become responses."""

from __future__ import annotations

import logging
import secrets
import sqlite3
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger("ssb.errors")


class AppError(Exception):
    """An error whose message is safe and useful to show to the user."""

    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None,
                 fields: dict[str, str] | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.fields = fields or {}
        self.details = details or {}


class ValidationError(AppError):
    status = 400
    code = "validation_error"


class NotFoundError(AppError):
    status = 404
    code = "not_found"


class ConflictError(AppError):
    status = 409
    code = "conflict"


class AuthRequired(AppError):
    status = 401
    code = "admin_required"


class DatabaseStartupError(Exception):
    """The database could not be opened/verified at startup."""

    def __init__(self, reason: str, corrupt: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.corrupt = corrupt


def ok(message: str = "", data: Any = None, status: int = 200):
    """Standard success envelope."""
    return jsonify({"success": True, "message": message, "data": data}), status


def fail(code: str, message: str, status: int = 400, fields: dict | None = None,
         details: dict | None = None, ref: str | None = None):
    """Standard error envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    if details:
        error["details"] = details
    if ref:
        error["ref"] = ref
    return jsonify({"success": False, "message": message, "error": error}), status


def wants_json() -> bool:
    return request.path.startswith("/api/") or request.path == "/healthz" or \
        request.accept_mimetypes.best == "application/json"


def _respond(code: str, message: str, status: int, *, fields=None, details=None, ref=None, title=None):
    if wants_json():
        return fail(code, message, status, fields, details, ref)
    return render_template("error.html", title=title or "Something went wrong",
                           message=message, status=status, ref=ref), status


_HTTP_MESSAGES = {
    400: "The request could not be understood.",
    403: "This action was not allowed.",
    404: "That page does not exist.",
    405: "That action is not supported here.",
    413: "The upload is too large.",
}


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return _respond(error.code, error.message, error.status, fields=error.fields, details=error.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        status = error.code or 500
        message = _HTTP_MESSAGES.get(status, "The request could not be completed.")
        return _respond(f"http_{status}", message, status)

    @app.errorhandler(sqlite3.Error)
    def handle_database_error(error: sqlite3.Error):
        ref = secrets.token_hex(3)
        log.exception("Database error [ref %s]: %s", ref, error)
        return _respond("database_unavailable",
                        "The school-bag database is temporarily unavailable. Try again in a moment.",
                        503, ref=ref, title="Database unavailable")

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        ref = secrets.token_hex(3)
        log.exception("Unexpected error [ref %s]: %s", ref, error)
        return _respond("internal_error",
                        "Something unexpected went wrong. The details were saved to the log.",
                        500, ref=ref)
