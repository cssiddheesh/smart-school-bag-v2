import unittest

from app.utils import normalize_uid, validate_uid
from app.errors import ValidationError
from tests.helpers import AppCase

FIVE = ["English", "Mathematics", "Science", "Computer Science", "Tamil"]


class UidTests(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(normalize_uid(" ab:12-cd \n"), "AB12CD")
        self.assertEqual(normalize_uid("0004567890"), "0004567890")  # leading zeros survive
        self.assertEqual(normalize_uid(None), "")
        self.assertEqual(normalize_uid("\x02ab12\r\n"), "AB12")

    def test_validation(self):
        self.assertEqual(validate_uid("ab-12-cd"), "AB12CD")
        for bad in ("", "   ", "AB", "x" * 33, "!!!!"):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                validate_uid(bad)


class ScanPipelineTests(AppCase):
    def setUp(self):
        super().setUp()
        for index, name in enumerate(FIVE, start=1):
            self.card(name, f"CARD000{index}")

    def test_spec_example_three_of_five_is_sixty_percent_not_ready(self):
        for uid in ("CARD0001", "CARD0002", "CARD0004"):  # English, Mathematics, Computer Science
            self.assertEqual(self.scan(uid)["outcome"], "accepted")
        state = self.state()
        self.assertEqual((state["required_count"], state["packed_count"], len(state["missing"]), state["percentage"]),
                         (5, 3, 2, 60))
        self.assertEqual(state["status"], "BAG NOT READY")
        self.assertEqual(state["missing"], ["Science", "Tamil"])
        self.assertFalse(state["ready"])

    def test_all_books_means_bag_ready(self):
        results = [self.scan(f"CARD000{i}") for i in range(1, 6)]
        self.assertEqual([r["became_ready"] for r in results], [False] * 4 + [True])
        state = self.state()
        self.assertEqual((state["status"], state["percentage"], state["phase"]), ("BAG READY", 100, "ready"))

    def test_messages_for_each_outcome(self):
        self.no_debounce()
        self.assertEqual(self.scan("CARD0002")["message"], "Mathematics detected")
        self.assertEqual(self.scan("CARD0002")["message"], "Mathematics already scanned")
        self.assertEqual(self.scan("NOSUCHCARD")["message"], "Unknown RFID card")

    def test_unknown_card_is_recorded_but_not_counted(self):
        self.scan("CARD0001")
        result = self.scan("FFFF0000")
        self.assertEqual(result["outcome"], "unknown_card")
        self.assertEqual(self.state()["packed_count"], 1)
        self.assertEqual(self.sql("SELECT outcome FROM scan_history ORDER BY id DESC LIMIT 1")[0][0], "unknown_card")

    def test_duplicate_does_not_change_progress(self):
        self.no_debounce()
        self.scan("CARD0001")
        self.assertEqual(self.scan("CARD0001")["outcome"], "duplicate")
        self.assertEqual(self.state()["packed_count"], 1)

    def test_held_card_is_debounced_for_hardware_but_not_for_simulation(self):
        self.assertEqual(self.scan("CARD0001")["outcome"], "accepted")
        repeat = self.scan("CARD0001")
        self.assertEqual((repeat["outcome"], repeat["recorded"]), ("debounced", False))
        self.assertEqual(self.scan("CARD0001", "SIMULATION")["outcome"], "duplicate")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM scan_history")[0][0], 2)  # debounced read not stored

    def test_book_not_on_todays_timetable_is_extra_and_does_not_count(self):
        self.s.books.add("Art")
        self.card("Art", "ART00001")
        result = self.scan("ART00001")
        self.assertEqual((result["outcome"], result["message"]), ("not_required", "Art is not required today"))
        state = self.state()
        self.assertEqual((state["extras"], state["packed_count"]), (["Art"], 0))

    def test_disabled_book_is_ignored(self):
        self.s.books.set_active(self.book("Tamil")["id"], False)
        self.assertEqual(self.scan("CARD0005")["outcome"], "disabled")
        self.assertEqual(self.state()["required_count"], 4)

    def test_uid_is_normalised_before_lookup(self):
        self.assertEqual(self.scan(" card-0001 ")["outcome"], "accepted")

    def test_malformed_reads_are_ignored_not_stored(self):
        for junk in ("", "A", "x" * 100):
            self.assertEqual(self.scan(junk)["outcome"], "ignored")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM scan_history")[0][0], 0)

    def test_without_auto_start_a_scan_needs_a_session(self):
        self.s.settings.update({"auto_start_session": False})
        result = self.scan("CARD0001")
        self.assertEqual((result["outcome"], result["message"]), ("no_session", "Start a packing session first"))
        self.s.sessions.start()
        self.assertEqual(self.scan("CARD0001", "SIMULATION")["outcome"], "accepted")

    def test_simulated_scans_use_the_same_pipeline_and_are_labelled(self):
        book = self.book("Science")
        self.s.books.remove_uid(book["id"])  # no real card: falls back to the reserved SIM<id> UID
        result = self.scan(f"SIM{book['id']}", "SIMULATION")
        self.assertEqual((result["outcome"], result["source"]), ("accepted", "SIMULATION"))
        self.assertEqual(self.sql("SELECT source FROM scan_history")[0][0], "SIMULATION")
        self.assertEqual(self.scan(f"SIM{book['id']}", "RFID")["outcome"], "unknown_card")  # SIM UIDs only work in demo

    def test_session_flags_mixed_sources(self):
        self.scan("CARD0001", "RFID")
        self.scan("CARD0002", "SIMULATION")
        session = self.state()["session"]
        self.assertTrue(session["has_real"] and session["has_simulated"])

    def test_capture_takes_the_next_card_instead_of_scanning_it(self):
        self.s.scans.start_capture()
        self.assertTrue(self.s.scans.capture_active())
        self.assertEqual(self.scan("NEWCARD99")["outcome"], "captured")
        self.assertEqual(self.s.scans.capture_status()["uid"], "NEWCARD99")
        self.assertEqual(self.s.scans.capture_status(), {"active": False, "uid": None, "seconds_left": 0})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM scan_history")[0][0], 0)

    def test_scan_survives_a_restart_of_the_services(self):
        self.scan("CARD0001")
        from app import create_app
        again = create_app({"DATA_DIR": self.root, "DATABASE_PATH": self.root / "test.db",
                            "BACKUP_DIR": self.root / "backups", "LOG_DIR": self.root / "logs", "START_READER": False})
        state = again.extensions["ssb"].state.snapshot()
        self.assertEqual((state["packed_count"], state["session"]["id"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
