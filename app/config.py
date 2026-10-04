"""Deployment-level configuration.

Only things that differ between machines live here (paths, host, port). Everything a
user may want to change while the app is running (school name, reader type, ...)
is a *setting* stored in the database - see ``services/settings_service.py``.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
APP_VERSION = "2.0.0"


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def load_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the Flask config dict from environment variables plus ``overrides``."""
    env = os.environ
    data_dir = Path(env.get("SCHOOLBAG_DATA_DIR") or BASE_DIR / "data").expanduser()
    config: dict[str, Any] = {
        "APP_VERSION": APP_VERSION,
        "DATA_DIR": data_dir,
        "DATABASE_PATH": Path(env.get("SCHOOLBAG_DATABASE") or data_dir / "schoolbag.db").expanduser(),
        "BACKUP_DIR": data_dir / "backups",
        "LOG_DIR": data_dir / "logs",
        "HOST": env.get("SCHOOLBAG_HOST", "0.0.0.0"),
        "PORT": _int(env.get("SCHOOLBAG_PORT"), 5000),
        "LOG_LEVEL": env.get("SCHOOLBAG_LOG_LEVEL", "INFO").upper(),
        "SECRET_KEY": env.get("FLASK_SECRET_KEY") or None,
        "START_READER": True,
        # Request limits: forms are tiny; only database restore may upload a file.
        "MAX_CONTENT_LENGTH": 64 * 1024,
        "MAX_RESTORE_BYTES": 32 * 1024 * 1024,
        "SESSION_COOKIE_NAME": "ssb_session",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SEND_FILE_MAX_AGE_DEFAULT": 12 * 3600,
    }
    if overrides:
        config.update(overrides)
    return config


def load_secret_key(data_dir: Path) -> str:
    """Return a persistent random secret key, creating it (mode 0600) on first run."""
    path = data_dir / "secret_key"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    return value
