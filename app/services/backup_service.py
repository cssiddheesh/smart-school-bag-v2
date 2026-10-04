"""Local database backups: create, list, download-safe lookup, validate, restore."""

from __future__ import annotations

import logging
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..bus import StateBus
from ..db import SQLITE_HEADER, Database, backup_to, initialize, ro_uri
from ..errors import NotFoundError, ValidationError
from ..utils import format_local, utc_iso, utcnow
from .event_service import EventService
from .settings_service import SettingsService

log = logging.getLogger("ssb.backup")

_NAME_RE = re.compile(r"^schoolbag-\d{8}-\d{6}(?:-[a-z]+)*\.db$")
_AUTO_LABELS = ("auto-upgrade", "pre-restore", "pre-clear")
_KEEP_AUTO = 10
_REQUIRED_TABLES = {"books", "settings", "scan_history"}


class BackupService:
    def __init__(self, db: Database, backup_dir: Path, bus: StateBus, events: EventService,
                 settings: SettingsService):
        self.db, self.dir, self.bus, self.events, self.settings = db, Path(backup_dir), bus, events, settings

    # ------------------------------------------------------------ create / list / lookup
    def create(self, label: str = "manual") -> Path:
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        target = self.dir / f"schoolbag-{stamp}-{label}.db"
        counter = 1
        while target.exists():
            counter += 1
            target = self.dir / f"schoolbag-{stamp}-{label}-{'x' * counter}.db"
        backup_to(self.db.path, target)
        self.events.log("info", "backup", f"Backup created: {target.name}")
        self._prune()
        return target

    def list(self) -> list[dict]:
        tz = self.settings.get("timezone")
        items = []
        if self.dir.exists():
            for path in sorted(self.dir.glob("schoolbag-*.db"), reverse=True):
                if _NAME_RE.match(path.name):
                    stat = path.stat()
                    items.append({"name": path.name, "size_kb": max(1, stat.st_size // 1024),
                                  "created": format_local(utc_iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                                                          tz, "%d %b %Y, %H:%M")})
        return items

    def path_for(self, name: str) -> Path:
        """Resolve a user-supplied backup name; only server-generated names are accepted."""
        if not _NAME_RE.match(name or ""):
            raise NotFoundError("That backup does not exist.")
        path = self.dir / name
        if not path.is_file():
            raise NotFoundError("That backup does not exist.")
        return path

    def delete(self, name: str) -> None:
        self.path_for(name).unlink()
        self.events.log("info", "backup", f"Backup deleted: {name}")

    def _prune(self) -> None:
        auto = [p for p in sorted(self.dir.glob("schoolbag-*.db"), reverse=True)
                if _NAME_RE.match(p.name) and any(f"-{label}" in p.name for label in _AUTO_LABELS)]
        for old in auto[_KEEP_AUTO:]:
            try:
                old.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ validation / restore
    def validate(self, path: Path) -> None:
        """Raise ValidationError unless ``path`` is a healthy database this app can use."""
        from ..migrations import LATEST_VERSION
        try:
            with path.open("rb") as handle:
                if handle.read(16) != SQLITE_HEADER:
                    raise ValidationError("That file is not a SQLite database.")
            conn = sqlite3.connect(ro_uri(path), timeout=5.0)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValidationError("That backup is damaged and can't be restored.")
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            raise ValidationError("That file is not a readable database.") from None
        if not _REQUIRED_TABLES <= tables:
            raise ValidationError("That file is not a Smart School Bag database.")
        if version > LATEST_VERSION:
            raise ValidationError("That backup was made by a newer version of the app.")

    def restore_path(self, source: Path, *, backup_dir: Path | None = None, database_failed: bool = False) -> None:
        self.validate(source)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        if database_failed:
            # Keep the unusable file for forensics; it is never deleted automatically.
            for suffix in ("", "-wal", "-shm"):
                old = Path(str(self.db.path) + suffix)
                if old.exists():
                    old.rename(self.db.path.with_name(f"{self.db.path.stem}.corrupt-{stamp}{self.db.path.suffix}{suffix}"))
            shutil.copyfile(source, self.db.path)
        else:
            self.create("pre-restore")
            src = sqlite3.connect(ro_uri(source), timeout=5.0)
            try:
                dst = sqlite3.connect(self.db.path, timeout=10.0)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        initialize(self.db, backup_dir or self.dir)
        self.settings.invalidate()
        self.bus.bump()
        self.events.log("warning", "backup", "Database restored from a backup")

    def restore_named(self, name: str, *, database_failed: bool = False) -> None:
        self.restore_path(self.path_for(name), database_failed=database_failed)

    def restore_upload(self, file_storage, *, database_failed: bool = False) -> None:
        if file_storage is None or not getattr(file_storage, "filename", ""):
            raise ValidationError("Choose a backup file to restore.", fields={"backup_file": "Required"})
        self.dir.mkdir(parents=True, exist_ok=True)
        temp = self.dir / f".upload-{secrets.token_hex(6)}.tmp"
        try:
            file_storage.save(temp)
            self.restore_path(temp, database_failed=database_failed)
        finally:
            temp.unlink(missing_ok=True)

    def start_fresh(self) -> None:
        """Move an unusable database aside and create a new empty one."""
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            old = Path(str(self.db.path) + suffix)
            if old.exists():
                old.rename(self.db.path.with_name(f"{self.db.path.stem}.corrupt-{stamp}{self.db.path.suffix}{suffix}"))
        initialize(self.db, self.dir)
        self.settings.invalidate()
        self.bus.bump()
        self.events.log("warning", "backup", "Started a new database (the old file was kept)")
