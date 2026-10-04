"""Background thread that owns the reader, reconnects after unplugging, and reports an
HONEST status. Reads are handed to ``on_uid`` (the scan pipeline)."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from ..utils import utc_iso
from .base import ReaderDisconnected, ReaderError, ReaderStatus, ReaderUnavailable, RFIDReader

log = logging.getLogger("ssb.reader")

RETRY_DELAYS = (2, 5, 10, 15)


def build_reader(settings: dict[str, Any]) -> Optional[RFIDReader]:
    kind = settings.get("reader_type", "none")
    if kind == "keyboard":
        from .keyboard import KeyboardWedgeReader
        return KeyboardWedgeReader(settings.get("reader_device", ""))
    if kind == "serial":
        from .serial_line import SerialLineReader
        return SerialLineReader(settings.get("reader_device", ""), int(settings.get("reader_baud", 9600)))
    return None


class ReaderManager:
    def __init__(self, get_settings: Callable[[], dict[str, Any]], on_uid: Callable[[str], Any],
                 on_status: Callable[[dict], None] | None = None,
                 factory: Callable[[dict[str, Any]], Optional[RFIDReader]] = build_reader):
        self._get_settings = get_settings
        self._on_uid = on_uid
        self._on_status = on_status
        self._factory = factory
        self._lock = threading.Lock()
        self._stop: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._raw: deque[dict[str, str]] = deque(maxlen=15)
        self._state = ReaderStatus.DISABLED
        self._message = "No reader configured."
        self._reader_name = ""
        self._since = utc_iso()
        self._last_read_at: Optional[str] = None

    # ------------------------------------------------------------ public
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self._state.value, "message": self._message, "reader": self._reader_name,
                    "since": self._since, "last_read_at": self._last_read_at}

    def raw_log(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._raw)

    def start(self) -> None:
        self.stop()
        stop = threading.Event()
        thread = threading.Thread(target=self._run, args=(stop,), name="rfid-reader", daemon=True)
        with self._lock:
            self._stop, self._thread = stop, thread
        thread.start()

    def stop(self) -> None:
        with self._lock:
            stop, thread = self._stop, self._thread
            self._stop = self._thread = None
        if stop:
            stop.set()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)

    def reconfigure(self) -> None:
        """Apply new reader settings. Does nothing if the reader was never started."""
        with self._lock:
            running = self._thread is not None
        if running:
            log.info("Reader settings changed; restarting reader")
            self.start()

    # ------------------------------------------------------------ internals
    def _set(self, state: ReaderStatus, message: str, reader_name: str = "") -> None:
        with self._lock:
            changed = (state, message) != (self._state, self._message)
            if changed:
                self._state, self._message, self._reader_name, self._since = state, message, reader_name, utc_iso()
        if changed:
            level = "info" if state in (ReaderStatus.CONNECTED, ReaderStatus.DISABLED) else "warning"
            log.log(logging.INFO if level == "info" else logging.WARNING, "Reader %s: %s", state.value, message)
            if self._on_status:
                try:
                    self._on_status(self.status())
                except Exception:
                    log.exception("Reader status callback failed")

    def _run(self, stop: threading.Event) -> None:
        attempt = 0
        while not stop.is_set():
            reader: Optional[RFIDReader] = None
            delay = 1.0
            try:
                reader = self._factory(self._get_settings())
                if reader is None:
                    self._set(ReaderStatus.DISABLED, "No reader configured.")
                    return
                reader.open()
                self._set(ReaderStatus.CONNECTED, "Reading cards.", reader.name)
                attempt = 0
                while not stop.is_set():
                    raw = reader.read_uid(0.5)
                    if raw:
                        with self._lock:
                            self._raw.appendleft({"time": utc_iso(), "raw": repr(raw)})
                            self._last_read_at = utc_iso()
                        try:
                            self._on_uid(raw)
                        except Exception:
                            log.exception("Scan processing failed")
            except ReaderUnavailable as error:
                self._set(ReaderStatus.UNAVAILABLE, str(error), reader.name if reader else "")
                delay = 30
            except ReaderDisconnected as error:
                self._set(ReaderStatus.DISCONNECTED, str(error), reader.name if reader else "")
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                attempt += 1
            except (ReaderError, Exception) as error:  # noqa: BLE001 - never let the thread die silently
                log.exception("Unexpected reader failure")
                self._set(ReaderStatus.ERROR, f"Unexpected reader error: {error}", reader.name if reader else "")
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                attempt += 1
            finally:
                if reader is not None:
                    reader.close()
            stop.wait(delay)
