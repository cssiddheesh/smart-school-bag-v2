"""Helpers shared by route modules."""

from __future__ import annotations

import functools
from typing import Any, Callable

from flask import current_app, flash, redirect, request, url_for

from .errors import AppError, ValidationError
from .utils import safe_next


def svc():
    """The service container for the running app."""
    return current_app.extensions["ssb"]


def json_body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is None and not request.data:
        return {}
    if not isinstance(payload, dict):
        raise ValidationError("The request body must be a JSON object.")
    return payload


def int_value(raw: Any, field: str, label: str) -> int:
    try:
        if isinstance(raw, bool):
            raise ValueError
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} is invalid.", fields={field: "Invalid"}) from None


def form_action(fallback_endpoint: str = "pages.dashboard") -> Callable:
    """For HTML form posts: turn a user-facing error into a flash message + redirect."""
    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            try:
                return view(*args, **kwargs)
            except AppError as error:
                flash(error.message, "error")
                return redirect(return_target(fallback_endpoint))
        return wrapper
    return decorator


def return_target(fallback_endpoint: str, **values: Any) -> str:
    return safe_next(request.form.get("return_to"), url_for(fallback_endpoint, **values))


def page_numbers(total: int, page: int, per_page: int) -> dict[str, int]:
    pages = max(1, -(-total // per_page))
    return {"page": min(max(1, page), pages), "pages": pages, "total": total, "per_page": per_page}
