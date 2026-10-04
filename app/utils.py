"""Small, dependency-free helpers shared across the application."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationError

UID_MIN_LEN = 4
UID_MAX_LEN = 32
DEFAULT_TIMEZONE = "Asia/Kolkata"


# ---------------------------------------------------------------- time
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(moment: Optional[datetime] = None) -> str:
    """UTC timestamp as ISO-8601 (what the database stores)."""
    return (moment or utcnow()).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=16)
def get_zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return timezone.utc


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def format_local(value: str | None, tz_name: str, fmt: str = "%d %b %Y, %H:%M:%S") -> str:
    """Render a stored UTC timestamp in the configured timezone."""
    moment = parse_iso(value)
    if moment is None:
        return "-"
    return moment.astimezone(get_zone(tz_name)).strftime(fmt)


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


def seconds_between(start_iso: str | None, end_iso: str | None) -> Optional[int]:
    start, end = parse_iso(start_iso), parse_iso(end_iso)
    if not start or not end:
        return None
    return max(0, int((end - start).total_seconds()))


# ---------------------------------------------------------------- RFID UIDs
def normalize_uid(raw: object) -> str:
    """Trim, upper-case and strip separators/control characters from a card UID.

    The result is always a *string* so leading zeros (common on 125 kHz cards that
    print decimal IDs such as ``0004567890``) are never lost.
    """
    text = unicodedata.normalize("NFKC", str(raw if raw is not None else ""))
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def validate_uid(raw: object) -> str:
    uid = normalize_uid(raw)
    if not uid:
        raise ValidationError("Enter the card's UID.", fields={"rfid_uid": "Required"})
    if not UID_MIN_LEN <= len(uid) <= UID_MAX_LEN:
        raise ValidationError(
            f"A card UID must be {UID_MIN_LEN}-{UID_MAX_LEN} letters or digits.",
            fields={"rfid_uid": "Invalid length"})
    return uid


def mask_uid(uid: str) -> str:
    """Shorten a UID for logs (``****A1B2``)."""
    return uid if len(uid) <= 4 else "****" + uid[-4:]


# ---------------------------------------------------------------- text input
def clean_text(raw: object, field: str, label: str, *, max_len: int, required: bool = True) -> str:
    text = unicodedata.normalize("NFKC", str(raw if raw is not None else ""))
    text = "".join(ch for ch in text if ch.isprintable())
    text = re.sub(r"\s+", " ", text).strip()
    if required and not text:
        raise ValidationError(f"{label} is required.", fields={field: "Required"})
    if len(text) > max_len:
        raise ValidationError(f"{label} must be {max_len} characters or fewer.", fields={field: "Too long"})
    return text


def to_int(raw: object, field: str, label: str, *, minimum: int | None = None,
           maximum: int | None = None) -> int:
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{label} must be a whole number.", fields={field: "Invalid"}) from None
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ValidationError(f"{label} is out of range.", fields={field: "Out of range"})
    return number


def safe_next(candidate: str | None, fallback: str) -> str:
    """Only allow same-site relative redirects."""
    if not candidate:
        return fallback
    parsed = urlparse(candidate)
    if (candidate.startswith("/") and not candidate.startswith("//") and "\\" not in candidate
            and not parsed.netloc and not parsed.scheme and "\n" not in candidate and "\r" not in candidate):
        return candidate
    return fallback
