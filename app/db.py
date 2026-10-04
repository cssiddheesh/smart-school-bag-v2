"""SQLite access: connections, transactions, migrations, integrity and backups."""

from __future__ import annotations

import logging
import sqlite3
from urllib.parse import quote
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import DatabaseStartupError
from .utils import utcnow

log = logging.getLogger("ssb.db")

SQLITE_HEADER = b"SQLite format 3\x00"


def ro_uri(path: Path) -> str:
    """A read-only SQLite URI that is safe for paths containing spaces, # or ?."""
    return f"file:{quote(str(Path(path).resolve()))}?mode=ro"


class Database:
    """Opens short-lived connections to one SQLite file.

    * ``read()``  - a connection for SELECTs.
    * ``write()`` - a connection inside ``BEGIN IMMEDIATE`` ... ``COMMIT`` (rolls back on error).

    WAL mode lets the RFID reader thread and web requests work at the same time.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        finally:
            conn.close()


def backup_to(source: Path, destination: Path) -> None:
    """Consistent copy of a (possibly in-use) database using SQLite's backup API."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(ro_uri(source), uri=True, timeout=5.0)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _has_user_tables(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    conn = sqlite3.connect(ro_uri(path), uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0] > 0
    finally:
        conn.close()


def check_integrity(path: Path) -> None:
    """Raise DatabaseStartupError if an existing file is not a healthy database."""
    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        with path.open("rb") as handle:
            if handle.read(16) != SQLITE_HEADER:
                raise DatabaseStartupError("The database file is not a valid SQLite database.", corrupt=True)
        conn = sqlite3.connect(ro_uri(path), uri=True, timeout=5.0)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except DatabaseStartupError:
        raise
    except sqlite3.DatabaseError as error:
        raise DatabaseStartupError(f"The database failed its integrity check ({error}).", corrupt=True) from error
    except OSError as error:
        raise DatabaseStartupError(f"The database file cannot be read ({error}).") from error
    if result != "ok":
        raise DatabaseStartupError(f"The database failed its integrity check ({result}).", corrupt=True)


def initialize(db: Database, backup_dir: Path) -> None:
    """Verify the database and apply any pending migrations (never recreates it)."""
    from .migrations import LATEST_VERSION, MIGRATIONS

    check_integrity(db.path)
    try:
        with db.read() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.OperationalError as error:
        raise DatabaseStartupError(f"The database cannot be opened ({error}).") from error
    except sqlite3.DatabaseError as error:
        raise DatabaseStartupError(f"The database cannot be read ({error}).", corrupt=True) from error

    if version > LATEST_VERSION:
        raise DatabaseStartupError(
            f"This database was created by a newer version of the app (schema {version}).")

    pending = [(v, fn) for v, fn in MIGRATIONS if v > version]
    if not pending:
        log.info("Database is up to date (schema %d)", version)
        return

    if _has_user_tables(db.path):
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"schoolbag-{stamp}-auto-upgrade.db"
        try:
            backup_to(db.path, target)
            log.info("Pre-upgrade backup written to %s", target.name)
        except (sqlite3.Error, OSError) as error:
            raise DatabaseStartupError(f"Could not back up the database before upgrading ({error}).") from error

    try:
        conn = db.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        finally:
            conn.close()
        for number, migrate in pending:
            with db.write() as conn:
                log.info("Applying database migration %d", number)
                migrate(conn)
                conn.execute(f"PRAGMA user_version = {int(number)}")
    except sqlite3.Error as error:
        raise DatabaseStartupError(f"Database upgrade failed and was rolled back ({error}).") from error
    log.info("Database initialised (schema %d)", LATEST_VERSION)
