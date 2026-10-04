"""CSRF protection, security headers and the optional admin PIN."""

from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
import time
from typing import Callable

from flask import Flask, current_app, redirect, request, session, url_for

from .errors import AppError, AuthRequired
from .utils import safe_next

CSRF_KEY = "csrf"
UNLOCK_SECONDS = 30 * 60
PIN_ITERATIONS = 120_000
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60
_attempts: dict[str, list[float]] = {}

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


# ---------------------------------------------------------------- CSRF
def csrf_token() -> str:
    if CSRF_KEY not in session:
        session[CSRF_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_KEY]


class CSRFError(AppError):
    status = 403
    code = "csrf_failed"


def _check_csrf() -> None:
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get(CSRF_KEY, "")
    if not expected or not hmac.compare_digest(str(sent), str(expected)):
        raise CSRFError("Your session expired or the request was not trusted. Reload the page and try again.")


# ---------------------------------------------------------------- admin PIN
def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), PIN_ITERATIONS).hex()
    return f"pbkdf2${PIN_ITERATIONS}${salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest)


def pin_enabled() -> bool:
    return bool(current_app.extensions["ssb"].settings.get("admin_pin"))


def admin_unlocked() -> bool:
    return (not pin_enabled()) or session.get("admin_until", 0) > time.time()


def lockout_remaining(client: str) -> int:
    now = time.time()
    recent = [t for t in _attempts.get(client, []) if now - t < _LOCKOUT_SECONDS]
    _attempts[client] = recent
    if len(recent) >= _MAX_ATTEMPTS:
        return int(_LOCKOUT_SECONDS - (now - recent[0])) + 1
    return 0


def record_failure(client: str) -> None:
    _attempts.setdefault(client, []).append(time.time())


def unlock() -> None:
    session["admin_until"] = time.time() + UNLOCK_SECONDS


def lock() -> None:
    session.pop("admin_until", None)


def admin_required(view: Callable) -> Callable:
    """Protects admin pages/actions only when an admin PIN has been configured."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if admin_unlocked():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            raise AuthRequired("Enter the admin PIN to do this.")
        target = request.full_path.rstrip("?") if request.method == "GET" else None
        return redirect(url_for("auth.unlock", next=safe_next(target, url_for("pages.dashboard"))))
    return wrapper


# ---------------------------------------------------------------- wiring
def init_security(app: Flask) -> None:
    @app.before_request
    def _guard():
        if request.endpoint in app.config.get("LARGE_UPLOAD_ENDPOINTS", ()):
            request.max_content_length = app.config["MAX_RESTORE_BYTES"]
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            _check_csrf()

    @app.after_request
    def _headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response
