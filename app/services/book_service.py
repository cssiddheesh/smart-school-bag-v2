"""Business rules for books and their RFID cards."""

from __future__ import annotations

from ..bus import StateBus
from ..db import Database
from ..errors import ConflictError, NotFoundError
from ..repositories import books as repo
from ..repositories import timetable as timetable_repo
from ..utils import clean_text, mask_uid, utc_iso, validate_uid
from .event_service import EventService


class BookService:
    def __init__(self, db: Database, bus: StateBus, events: EventService):
        self.db, self.bus, self.events = db, bus, events

    def list_with_status(self, required_names_today: set[str] | None = None) -> list[dict]:
        with self.db.read() as conn:
            books = repo.list_all(conn)
        required = {n.casefold() for n in (required_names_today or set())}
        for book in books:
            book["assigned"] = bool(book["rfid_uid"])
            book["required_today"] = book["name"].casefold() in required and bool(book["is_active"])
        return books

    def list_active(self) -> list[dict]:
        with self.db.read() as conn:
            return repo.list_active(conn)

    @staticmethod
    def _get(conn, book_id: int) -> dict:
        book = repo.get(conn, book_id)
        if not book:
            raise NotFoundError("That book no longer exists.")
        return book

    def add(self, name: str) -> dict:
        name = clean_text(name, "name", "Book name", max_len=60)
        with self.db.write() as conn:
            if repo.get_by_name(conn, name):
                raise ConflictError(f"A book called “{name}” already exists.", fields={"name": "Duplicate"})
            book_id = repo.create(conn, name, utc_iso())
        self.bus.bump()
        self.events.log("info", "books", f"Book added: {name}")
        return {"id": book_id, "name": name}

    def rename(self, book_id: int, name: str) -> None:
        name = clean_text(name, "name", "Book name", max_len=60)
        with self.db.write() as conn:
            book = self._get(conn, book_id)
            other = repo.get_by_name(conn, name)
            if other and other["id"] != book_id:
                raise ConflictError(f"A book called “{name}” already exists.", fields={"name": "Duplicate"})
            repo.rename(conn, book_id, name, utc_iso())
        self.bus.bump()
        self.events.log("info", "books", f"Book renamed: {book['name']} -> {name}")

    def set_active(self, book_id: int, active: bool) -> None:
        with self.db.write() as conn:
            book = self._get(conn, book_id)
            repo.set_active(conn, book_id, active, utc_iso())
        self.bus.bump()
        self.events.log("info", "books", f"Book {'enabled' if active else 'disabled'}: {book['name']}")

    def assign_uid(self, book_id: int, raw_uid: str) -> bool:
        """Assign/replace a card. Returns True if it replaced an existing card."""
        uid = validate_uid(raw_uid)
        with self.db.write() as conn:
            book = self._get(conn, book_id)
            other = repo.get_by_uid(conn, uid)
            if other and other["id"] != book_id:
                raise ConflictError(f"That card is already assigned to “{other['name']}”.",
                                    fields={"rfid_uid": "Already in use"})
            replaced = bool(book["rfid_uid"]) and book["rfid_uid"] != uid
            repo.set_uid(conn, book_id, uid, utc_iso())
        self.bus.bump()
        self.events.log("info", "books", f"Card {mask_uid(uid)} assigned to {book['name']}")
        return replaced

    def remove_uid(self, book_id: int) -> None:
        with self.db.write() as conn:
            book = self._get(conn, book_id)
            repo.set_uid(conn, book_id, None, utc_iso())
        self.bus.bump()
        self.events.log("info", "books", f"Card unassigned from {book['name']}")

    def delete(self, book_id: int) -> None:
        with self.db.write() as conn:
            book = self._get(conn, book_id)
            used = repo.usage(conn, book_id)
            if any(used.values()):
                raise ConflictError(
                    f"“{book['name']}” is used in the timetable or history, so it can't be deleted. "
                    "Disable it instead.")
            repo.delete(conn, book_id)
        self.bus.bump()
        self.events.log("info", "books", f"Book deleted: {book['name']}")

    def names_required_on(self, day_id: int | None) -> set[str]:
        if day_id is None:
            return set()
        with self.db.read() as conn:
            return {r["name"] for r in timetable_repo.required_books(conn, day_id)}

