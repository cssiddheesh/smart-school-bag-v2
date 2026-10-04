"""Business rules for the editable timetable (days and ordered periods)."""

from __future__ import annotations

from ..bus import StateBus
from ..db import Database
from ..errors import ConflictError, NotFoundError, ValidationError
from ..repositories import books as books_repo
from ..repositories import timetable as repo
from ..utils import clean_text
from .event_service import EventService


class TimetableService:
    def __init__(self, db: Database, bus: StateBus, events: EventService):
        self.db, self.bus, self.events = db, bus, events

    def days(self) -> list[dict]:
        with self.db.read() as conn:
            return repo.list_days(conn)

    def day_view(self, day_id: int) -> dict:
        with self.db.read() as conn:
            day = repo.get_day(conn, day_id)
            if not day:
                raise NotFoundError("That day does not exist in the timetable.")
            return {**day, "entries": repo.entries(conn, day_id), "required": repo.required_books(conn, day_id)}

    # ------------------------------------------------------------ days
    def add_day(self, name: str) -> int:
        name = clean_text(name, "name", "Day name", max_len=30)
        with self.db.write() as conn:
            if repo.get_day_by_name(conn, name):
                raise ConflictError(f"“{name}” is already in the timetable.", fields={"name": "Duplicate"})
            day_id = repo.create_day(conn, name)
        self.bus.bump()
        self.events.log("info", "timetable", f"Day added: {name}")
        return day_id

    def rename_day(self, day_id: int, name: str) -> None:
        name = clean_text(name, "name", "Day name", max_len=30)
        with self.db.write() as conn:
            day = self._day(conn, day_id)
            other = repo.get_day_by_name(conn, name)
            if other and other["id"] != day_id:
                raise ConflictError(f"“{name}” is already in the timetable.", fields={"name": "Duplicate"})
            repo.rename_day(conn, day_id, name)
        self.bus.bump()
        self.events.log("info", "timetable", f"Day renamed: {day['name']} -> {name}")

    def delete_day(self, day_id: int) -> None:
        with self.db.write() as conn:
            day = self._day(conn, day_id)
            if repo.day_session_count(conn, day_id):
                raise ConflictError(f"{day['name']} has packing history, so it can't be deleted. "
                                    "Remove its periods or rename it instead.")
            if len(repo.list_days(conn)) <= 1:
                raise ConflictError("The timetable needs at least one day.")
            repo.delete_day(conn, day_id)
        self.bus.bump()
        self.events.log("info", "timetable", f"Day deleted: {day['name']}")

    def move_day(self, day_id: int, direction: str) -> None:
        with self.db.write() as conn:
            self._day(conn, day_id)
            ids = [d["id"] for d in repo.list_days(conn)]
            self._swap(ids, day_id, direction)
            repo.renumber_days(conn, ids)
        self.bus.bump()

    # ------------------------------------------------------------ periods
    def add_entry(self, day_id: int, book_id: int) -> None:
        with self.db.write() as conn:
            day = self._day(conn, day_id)
            book = books_repo.get(conn, book_id)
            if not book:
                raise ValidationError("Choose a book for the period.", fields={"book_id": "Required"})
            if not book["is_active"]:
                raise ValidationError(f"“{book['name']}” is disabled. Enable it first.", fields={"book_id": "Disabled"})
            repo.add_entry(conn, day_id, book_id)
        self.bus.bump()
        self.events.log("info", "timetable", f"{book['name']} added to {day['name']}")

    def set_entry_book(self, entry_id: int, book_id: int) -> None:
        with self.db.write() as conn:
            entry = self._entry(conn, entry_id)
            book = books_repo.get(conn, book_id)
            if not book or not book["is_active"]:
                raise ValidationError("Choose an enabled book.", fields={"book_id": "Invalid"})
            repo.set_entry_book(conn, entry_id, book_id)
        self.bus.bump()

    def remove_entry(self, entry_id: int) -> None:
        with self.db.write() as conn:
            entry = self._entry(conn, entry_id)
            repo.delete_entry(conn, entry_id)
            repo.renumber_entries(conn, entry["day_id"], [e["id"] for e in repo.entries(conn, entry["day_id"])])
        self.bus.bump()

    def move_entry(self, entry_id: int, direction: str) -> None:
        with self.db.write() as conn:
            entry = self._entry(conn, entry_id)
            ids = [e["id"] for e in repo.entries(conn, entry["day_id"])]
            self._swap(ids, entry_id, direction)
            repo.renumber_entries(conn, entry["day_id"], ids)
        self.bus.bump()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _swap(ids: list[int], target: int, direction: str) -> None:
        if direction not in ("up", "down"):
            raise ValidationError("Direction must be up or down.")
        index = ids.index(target)
        other = index - 1 if direction == "up" else index + 1
        if 0 <= other < len(ids):
            ids[index], ids[other] = ids[other], ids[index]

    @staticmethod
    def _day(conn, day_id: int) -> dict:
        day = repo.get_day(conn, day_id)
        if not day:
            raise NotFoundError("That day does not exist in the timetable.")
        return day

    @staticmethod
    def _entry(conn, entry_id: int) -> dict:
        entry = repo.get_entry(conn, entry_id)
        if not entry:
            raise NotFoundError("That period no longer exists.")
        return entry
