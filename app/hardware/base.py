"""RFID reader abstraction. The rest of the app never talks to hardware directly."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class ReaderStatus(str, Enum):
    DISABLED = "disabled"          # no reader configured (reader type = none)
    UNAVAILABLE = "unavailable"    # configured, but can't work here (library/permission/setup missing)
    DISCONNECTED = "disconnected"  # configured, but the device is not present (or was unplugged)
    CONNECTED = "connected"        # the device was opened successfully and is being read
    ERROR = "error"                # opened, but reading failed unexpectedly


class ReaderError(Exception):
    """Base class for reader problems."""


class ReaderUnavailable(ReaderError):
    """The reader can't be used until something is installed/configured."""


class ReaderDisconnected(ReaderError):
    """The device is missing or has been unplugged."""


class RFIDReader(ABC):
    """One adapter per physical transport. Returns the raw text of one card read."""

    name = "reader"

    @abstractmethod
    def open(self) -> None:
        """Open the device. Raise ReaderUnavailable / ReaderDisconnected on failure."""

    @abstractmethod
    def read_uid(self, timeout: float) -> Optional[str]:
        """Block up to ``timeout`` seconds. Return raw card text, or None if nothing arrived."""

    @abstractmethod
    def close(self) -> None:
        """Release the device. Must be safe to call more than once."""
