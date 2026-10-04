import time
import unittest

from app.hardware.base import ReaderDisconnected, ReaderStatus, ReaderUnavailable, RFIDReader
from app.hardware.keyboard import KeyAssembler
from app.hardware.manager import ReaderManager
from tests.helpers import AppCase

KEYS = {"0": 11, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "A": 30, "F": 33}


def type_text(assembler, text, enter=True):
    out = None
    for ch in text:
        assembler.feed(KEYS[ch], 1)
        assembler.feed(KEYS[ch], 0)
    if enter:
        out = assembler.feed(28, 1)
    return out


class KeyAssemblerTests(unittest.TestCase):
    def test_reassembles_typed_card_number(self):
        self.assertEqual(type_text(KeyAssembler(), "0004567890"), "0004567890")
        self.assertEqual(type_text(KeyAssembler(), "1A2F"), "1A2F")

    def test_ignores_releases_repeats_and_lone_enter(self):
        a = KeyAssembler()
        a.feed(KEYS["1"], 1)
        a.feed(KEYS["1"], 2)  # auto-repeat
        a.feed(KEYS["1"], 0)
        self.assertEqual(a.feed(28, 1), "1")
        self.assertIsNone(a.feed(28, 1))

    def test_two_cards_in_a_row(self):
        a = KeyAssembler()
        self.assertEqual(type_text(a, "12"), "12")
        self.assertEqual(type_text(a, "34"), "34")


class FakeReader(RFIDReader):
    name = "Fake reader"

    def __init__(self, script, open_error=None):
        self.script, self.open_error = list(script), open_error
        self.closed = False

    def open(self):
        if self.open_error:
            raise self.open_error

    def read_uid(self, timeout):
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        time.sleep(0.02)
        return None

    def close(self):
        self.closed = True


def wait_for(condition, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


class ReaderManagerTests(unittest.TestCase):
    def manager(self, reader, got=None, states=None):
        got = got if got is not None else []
        return ReaderManager(lambda: {}, got.append, (lambda s: states.append(s["state"])) if states is not None else None,
                             factory=lambda cfg: reader)

    def test_not_configured_is_disabled_not_connected(self):
        m = ReaderManager(lambda: {}, lambda raw: None, factory=lambda cfg: None)
        m.start()
        self.assertTrue(wait_for(lambda: m.status()["state"] == "disabled"))
        m.stop()

    def test_connected_reader_delivers_raw_reads(self):
        got, states = [], []
        reader = FakeReader(["AABB1122", "CCDD3344"])
        m = self.manager(reader, got, states)
        m.start()
        self.assertTrue(wait_for(lambda: len(got) == 2))
        self.assertEqual(got, ["AABB1122", "CCDD3344"])
        self.assertEqual(m.status()["state"], ReaderStatus.CONNECTED.value)
        self.assertEqual([r["raw"] for r in m.raw_log()], ["'CCDD3344'", "'AABB1122'"])
        m.stop()
        self.assertTrue(reader.closed)
        self.assertIn("connected", states)

    def test_missing_device_is_reported_as_disconnected(self):
        m = self.manager(FakeReader([], ReaderDisconnected("/dev/ttyUSB0 was not found.")))
        m.start()
        self.assertTrue(wait_for(lambda: m.status()["state"] == "disconnected"))
        self.assertIn("not found", m.status()["message"])
        m.stop()

    def test_missing_prerequisite_is_unavailable(self):
        m = self.manager(FakeReader([], ReaderUnavailable("pyserial is not installed.")))
        m.start()
        self.assertTrue(wait_for(lambda: m.status()["state"] == "unavailable"))
        m.stop()

    def test_unplugging_while_running_changes_status(self):
        m = self.manager(FakeReader(["AABB1122", ReaderDisconnected("The reader was unplugged.")]))
        m.start()
        self.assertTrue(wait_for(lambda: m.status()["state"] == "disconnected"))
        m.stop()

    def test_unexpected_failure_is_error_and_thread_survives_bad_callbacks(self):
        def boom(raw):
            raise RuntimeError("downstream bug")
        m = ReaderManager(lambda: {}, boom, factory=lambda cfg: FakeReader(["AABB1122"]))
        m.start()
        self.assertTrue(wait_for(lambda: m.raw_log() != []))
        self.assertEqual(m.status()["state"], "connected")  # a processing bug does not look like a hardware fault
        m.stop()
        m2 = self.manager(FakeReader([], RuntimeError("weird")))
        m2.start()
        self.assertTrue(wait_for(lambda: m2.status()["state"] == "error"))
        m2.stop()

    def test_stop_is_prompt_and_idempotent(self):
        m = self.manager(FakeReader([]))
        m.start()
        wait_for(lambda: m.status()["state"] == "connected")
        started = time.time()
        m.stop()
        m.stop()
        self.assertLess(time.time() - started, 2)


class ReaderToPipelineTests(AppCase):
    def test_real_reader_scans_flow_through_the_same_pipeline_labelled_rfid(self):
        self.card("English", "AABB1122")
        self.card("Mathematics", "CCDD3344")
        reader = FakeReader(["aa:bb:11:22", "CCDD3344", "UNKNOWN99"])
        manager = ReaderManager(self.s.settings.get_all, lambda raw: self.s.scans.process(raw, "RFID"), factory=lambda cfg: reader)
        manager.start()
        self.assertTrue(wait_for(lambda: self.sql("SELECT COUNT(*) FROM scan_history")[0][0] == 3))
        manager.stop()
        state = self.state()
        self.assertEqual((state["packed_count"], state["missing"][0]), (2, "Science"))
        self.assertEqual({r[0] for r in self.sql("SELECT source FROM scan_history")}, {"RFID"})
        self.assertEqual(self.sql("SELECT outcome FROM scan_history ORDER BY id")[-1][0], "unknown_card")

    def test_dashboard_is_honest_when_hardware_is_missing(self):
        self.assertEqual(self.state()["reader"]["state"], "disabled")
        html = self.client().get("/").get_data(as_text=True)
        self.assertNotIn("<strong>Connected</strong>", html)


if __name__ == "__main__":
    unittest.main()
