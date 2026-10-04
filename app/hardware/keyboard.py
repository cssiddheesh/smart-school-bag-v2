"""EXPERIMENTAL - UNTESTED WITH REAL HARDWARE.

Many cheap 125 kHz USB readers pretend to be a USB keyboard: they "type" the card
number followed by Enter. This adapter reads Linux evdev events (``/dev/input/event*``)
using only the standard library and rebuilds that typed text.

It does NOT assume any particular card format - whatever digits/letters were typed
are returned as raw text and normalised by the scan pipeline.

Needs: Linux, read permission on the device (add the user to the ``input`` group).
"""

from __future__ import annotations

import os
import select
import struct
from typing import Optional

from .base import ReaderDisconnected, ReaderUnavailable, RFIDReader

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
_EVENT = struct.Struct("llHHi")
_EV_KEY = 0x01
_EVIOCGRAB = 0x40044590

_KEYS = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    71: "7", 72: "8", 73: "9", 75: "4", 76: "5", 77: "6", 79: "1", 80: "2", 81: "3", 82: "0",
}
_ENTER_CODES = {28, 96}


class KeyAssembler:
    """Turns a stream of (code, value) key events into complete card strings."""

    def __init__(self) -> None:
        self._buffer: list[str] = []

    def feed(self, code: int, value: int) -> Optional[str]:
        if value != 1:  # key press only (ignore release and auto-repeat)
            return None
        if code in _ENTER_CODES:
            text, self._buffer = "".join(self._buffer), []
            return text or None
        char = _KEYS.get(code)
        if char:
            self._buffer.append(char)
            if len(self._buffer) > 64:  # runaway input, drop it
                self._buffer.clear()
        return None


class KeyboardWedgeReader(RFIDReader):
    name = "USB keyboard-style reader"

    def __init__(self, device: str):
        self.device = device
        self._fd: Optional[int] = None
        self._assembler = KeyAssembler()

    def open(self) -> None:
        if not self.device:
            raise ReaderUnavailable("No device path set. Choose the reader's /dev/input/... path in Settings.")
        if os.name != "posix":
            raise ReaderUnavailable("Keyboard-style readers are only supported on Linux.")
        try:
            self._fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            raise ReaderDisconnected(f"{self.device} was not found. Is the reader plugged in?") from None
        except PermissionError:
            raise ReaderUnavailable(
                f"No permission to read {self.device}. Add the service user to the 'input' group.") from None
        except OSError as error:
            raise ReaderDisconnected(f"Cannot open {self.device}: {error}") from None
        try:  # keep the card digits from also being typed into other programs
            import fcntl
            fcntl.ioctl(self._fd, _EVIOCGRAB, 1)
        except OSError:
            pass

    def read_uid(self, timeout: float) -> Optional[str]:
        if self._fd is None:
            raise ReaderDisconnected("Reader is not open.")
        try:
            ready, _, _ = select.select([self._fd], [], [], timeout)
            if not ready:
                return None
            data = os.read(self._fd, _EVENT.size * 32)
        except (OSError, ValueError):
            raise ReaderDisconnected("The reader was unplugged or stopped responding.") from None
        if not data:
            raise ReaderDisconnected("The reader closed the connection.")
        for offset in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
            _, _, etype, code, value = _EVENT.unpack_from(data, offset)
            if etype == _EV_KEY:
                text = self._assembler.feed(code, value)
                if text:
                    return text
        return None

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
