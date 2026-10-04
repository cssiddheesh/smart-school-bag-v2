"""Read-only diagnostics for the Settings > System section."""

from __future__ import annotations

import platform
import time
from pathlib import Path

from ..db import Database


class SystemService:
    def __init__(self, db: Database, version: str):
        self.db, self.version, self._started = db, version, time.time()

    def info(self) -> dict:
        with self.db.read() as conn:
            schema = conn.execute("PRAGMA user_version").fetchone()[0]
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        path = Path(self.db.path)
        return {
            "version": self.version,
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "database_path": str(path),
            "database_kb": max(1, path.stat().st_size // 1024) if path.exists() else 0,
            "schema_version": schema,
            "journal_mode": journal,
            "uptime_minutes": int((time.time() - self._started) // 60),
        }
