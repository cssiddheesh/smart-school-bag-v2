"""SQL for the key/value ``settings`` table (values are JSON-encoded, as in v1)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_all(conn: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        try:
            result[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            result[row["key"]] = row["value"]
    return result


def set_many(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    conn.executemany(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(key, json.dumps(value)) for key, value in values.items()])
