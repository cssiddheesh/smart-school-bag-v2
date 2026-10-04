"""A tiny revision counter. Anything that changes visible state bumps it, and the
dashboard asks "has the revision changed?" instead of re-downloading everything."""

from __future__ import annotations

import threading


class StateBus:
    def __init__(self) -> None:
        self._revision = 1
        self._lock = threading.Lock()

    @property
    def revision(self) -> int:
        return self._revision

    def bump(self) -> int:
        with self._lock:
            self._revision += 1
            return self._revision
