"""EXPERIMENTAL - UNTESTED WITH REAL HARDWARE.

For readers that appear as a serial port (``/dev/ttyUSB0``, ``/dev/ttyACM0``) and
send each card as one line of text. Binary-framed readers are NOT supported - use
the Reader test panel in Settings to see what your reader actually sends.

Needs the optional ``pyserial`` package and membership of the ``dialout`` group.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import ReaderDisconnected, ReaderUnavailable, RFIDReader


class SerialLineReader(RFIDReader):
    name = "USB serial reader"

    def __init__(self, device: str, baud: int = 9600):
        self.device, self.baud = device, baud
        self._port: Any = None

    def open(self) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            raise ReaderUnavailable("pyserial is not installed. Run: pip install pyserial") from None
        if not self.device:
            raise ReaderUnavailable("No serial port set. Choose the reader's /dev/tty... port in Settings.")
        try:
            self._port = serial.Serial(self.device, self.baud, timeout=0.5)
        except serial.SerialException as error:
            text = str(error)
            if "ermission" in text:
                raise ReaderUnavailable(
                    f"No permission to open {self.device}. Add the service user to the 'dialout' group.") from None
            raise ReaderDisconnected(f"Cannot open {self.device}: {text}") from None

    def read_uid(self, timeout: float) -> Optional[str]:
        if self._port is None:
            raise ReaderDisconnected("Reader is not open.")
        try:
            self._port.timeout = timeout
            line = self._port.readline()
        except Exception:  # SerialException, OSError, TypeError after unplug
            raise ReaderDisconnected("The reader was unplugged or stopped responding.") from None
        text = line.decode("ascii", errors="ignore").strip()
        return text or None

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
