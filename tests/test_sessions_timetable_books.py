import unittest

from app.errors import ConflictError, NotFoundError, ValidationError
from tests.helpers import AppCase


class SessionTests(AppCase):
    def setUp(self):
        super().setUp()
        for i, name in enumerate(["English", "Mathematics", "Science", "Computer Science", "Tamil"], start=1):
            self.card(name, f"CARD000{i}")
        self.no_debounce()

    def test_start_then_second_start_is_rejected(self):
        first = self.s.sessions.start()
        with self.assertRaises(ConflictError) as ctx:
            self.s.sessions.start()
        self.assertEqual(ctx.exception.code, "session_active")
        self.assertEqual(self.state()["session"]["id"], first["id"])

    def test_reset_keeps_old_session_in_history_and_starts_clean(self):
        self.s.sessions.start()
        self.scan("CARD0001")
        fresh = self.s.sessions.reset()
        self.assertEqual(self.state()["packed_count"], 0)
        self.assertEqual(self.sql("SELECT status FROM packing_sessions WHERE id = 1")[0][0], "abandoned")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM scan_history WHERE session_id = 1")[0][0], 1)
        self.assertEqual(fresh["id"], 2)

    def test_complete_requires_a_ready_bag(self):
        self.s.sessions.start()
        self.scan("CARD0001")
        with self.assertRaises(ConflictError) as ctx:
            self.s.sessions.complete()
        self.assertEqual(ctx.exception.code, "not_ready")
        self.assertIn("Mathematics", ctx.exception.message)

    def test_complete_a_ready_bag_and_summarise(self):
        for i in range(1, 6):
            self.scan(f"CARD000{i}", "SIMULATION")
        self.scan("CARD0001", "SIMULATION")  # one duplicate
        done = self.s.sessions.complete()
        summary = self.s.sessions.summary(done["id"])
        self.assertEqual((summary["session"]["status"], summary["packed_count"], summary["percentage"]), ("completed", 5, 100))
        self.assertEqual((summary["counts"]["total"], summary["counts"]["duplicate"]), (6, 1))
        self.assertTrue(summary["has_simulated"] and not summary["has_real"])
        self.assertIsNotNone(summary["duration_seconds"])
        state = self.state()
        self.assertEqual((state["phase"], state["session"], state["last_session"]["status"]), ("idle", None, "completed"))

    def test_no_stale_state_leaks_into_a_new_day_or_session(self):
        self.scan("CARD0001")
        self.scan("CARD0002")
        tuesday = self.day("Tuesday")["id"]
        with self.assertRaises(ConflictError) as ctx:
            self.s.sessions.set_day(tuesday)
        self.assertEqual((ctx.exception.code, ctx.exception.details["scan_count"]), ("session_in_progress", 2))
        self.s.sessions.set_day(tuesday, confirm=True)
        state = self.state()
        self.assertEqual((state["day"]["name"], state["packed_count"], state["session"]), ("Tuesday", 0, None))
        self.scan("CARD0003")
        new = self.state()
        self.assertEqual((new["packed_count"], new["session"]["day_name"], new["session"]["id"]), (1, "Tuesday", 2))

    def test_same_day_selection_does_not_end_the_session(self):
        self.scan("CARD0001")
        self.s.sessions.set_day(self.day("Monday")["id"])
        self.assertEqual(self.state()["packed_count"], 1)

    def test_summary_of_unknown_session(self):
        with self.assertRaises(NotFoundError):
            self.s.sessions.summary(12345)

    def test_session_snapshot_keeps_original_requirements_after_timetable_edit(self):
        self.s.sessions.start()
        entry = self.s.timetable.day_view(self.day("Monday")["id"])["entries"][0]["id"]
        self.s.timetable.remove_entry(entry)
        self.assertEqual(self.state()["required_count"], 5)  # running session unchanged
        self.s.sessions.reset()
        self.assertEqual(self.state()["required_count"], 4)  # new session sees the edit


class TimetableTests(AppCase):
    def test_valid_invalid_and_empty_days(self):
        self.assertEqual(len(self.s.timetable.day_view(self.day("Friday")["id"])["required"]), 5)
        with self.assertRaises(NotFoundError):
            self.s.timetable.day_view(9999)
        saturday = self.s.timetable.add_day("Saturday")
        self.s.sessions.set_day(saturday)
        state = self.state()
        self.assertEqual((state["phase"], state["required_count"], state["status"]), ("empty", 0, "NO BOOKS TODAY"))
        with self.assertRaises(ValidationError):
            self.s.sessions.start()

    def test_add_edit_reorder_remove_periods(self):
        monday = self.day("Monday")["id"]
        art = self.s.books.add("Art")["id"]
        self.s.timetable.add_entry(monday, art)
        entries = self.s.timetable.day_view(monday)["entries"]
        self.assertEqual(entries[-1]["book_name"], "Art")
        self.s.timetable.move_entry(entries[-1]["id"], "up")
        self.assertEqual(self.s.timetable.day_view(monday)["entries"][-2]["book_name"], "Art")
        self.s.timetable.move_entry(self.s.timetable.day_view(monday)["entries"][0]["id"], "up")  # first stays first
        self.assertEqual(self.s.timetable.day_view(monday)["entries"][0]["book_name"], "English")
        self.s.timetable.set_entry_book(entries[0]["id"], art)
        self.assertEqual(self.s.timetable.day_view(monday)["entries"][0]["book_name"], "Art")
        self.s.timetable.remove_entry(entries[0]["id"])
        positions = [e["position"] for e in self.s.timetable.day_view(monday)["entries"]]
        self.assertEqual(positions, list(range(1, len(positions) + 1)))
        with self.assertRaises(ValidationError):
            self.s.timetable.move_entry(entries[1]["id"], "sideways")

    def test_repeated_subject_is_required_once(self):
        monday = self.day("Monday")["id"]
        self.s.timetable.add_entry(monday, self.book("English")["id"])
        view = self.s.timetable.day_view(monday)
        self.assertEqual((len(view["entries"]), len(view["required"])), (6, 5))

    def test_day_rules(self):
        with self.assertRaises(ConflictError):
            self.s.timetable.add_day("monday")
        friday = self.day("Friday")["id"]
        self.s.timetable.rename_day(friday, "Fri")
        self.s.sessions.set_day(friday)
        self.s.sessions.start()
        with self.assertRaises(ConflictError):  # has packing history
            self.s.timetable.delete_day(friday)
        self.s.timetable.move_day(self.day("Fri")["id"], "up")
        self.assertEqual([d["name"] for d in self.s.timetable.days()][3], "Fri")

    def test_disabled_book_cannot_be_added_to_a_period(self):
        book = self.book("Tamil")["id"]
        self.s.books.set_active(book, False)
        with self.assertRaises(ValidationError):
            self.s.timetable.add_entry(self.day("Monday")["id"], book)


class BookTests(AppCase):
    def test_duplicate_names_are_rejected_case_insensitively(self):
        with self.assertRaises(ConflictError):
            self.s.books.add("english")
        with self.assertRaises(ConflictError):
            self.s.books.rename(self.book("Tamil")["id"], "ENGLISH")
        self.s.books.rename(self.book("Tamil")["id"], "Tamil")  # renaming to itself is fine

    def test_uid_rules(self):
        self.card("English", "AAAA1111")
        with self.assertRaises(ConflictError) as ctx:
            self.s.books.assign_uid(self.book("Tamil")["id"], "aaaa-1111")
        self.assertIn("English", ctx.exception.message)
        for bad in ("", "abc", "z" * 40):
            with self.assertRaises(ValidationError):
                self.s.books.assign_uid(self.book("Tamil")["id"], bad)
        self.assertTrue(self.s.books.assign_uid(self.book("English")["id"], "BBBB2222"))  # replaced
        self.assertFalse(self.s.books.assign_uid(self.book("English")["id"], "BBBB2222"))  # same card again: not a replace
        self.s.books.remove_uid(self.book("English")["id"])
        self.assertFalse(self.book("English")["assigned"])

    def test_status_columns(self):
        monday = self.state()["checklist"]
        names = {b["name"] for b in monday}
        rows = {b["name"]: b for b in self.s.books.list_with_status(names)}
        self.assertTrue(rows["English"]["required_today"])
        self.s.books.add("Art")
        art = next(b for b in self.s.books.list_with_status(names) if b["name"] == "Art")
        self.assertEqual((art["required_today"], art["assigned"], art["is_active"]), (False, False, 1))

    def test_delete_only_unused_books(self):
        with self.assertRaises(ConflictError):
            self.s.books.delete(self.book("English")["id"])
        art = self.s.books.add("Art")["id"]
        self.s.books.delete(art)
        with self.assertRaises(NotFoundError):
            self.s.books.rename(art, "Art")

    def test_disable_removes_book_from_requirements(self):
        self.s.books.set_active(self.book("Tamil")["id"], False)
        self.assertEqual(self.state()["required_count"], 4)
        self.s.books.set_active(self.book("Tamil")["id"], True)
        self.assertEqual(self.state()["required_count"], 5)

    def test_names_are_cleaned(self):
        self.assertEqual(self.s.books.add("  History   of   Art  ")["name"], "History of Art")
        with self.assertRaises(ValidationError):
            self.s.books.add("   ")
        with self.assertRaises(ValidationError):
            self.s.books.add("x" * 61)


if __name__ == "__main__":
    unittest.main()
