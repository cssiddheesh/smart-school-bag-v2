"""Pure functions that decide packing progress and readiness (no I/O)."""

from __future__ import annotations

from typing import Iterable


def calculate_bag_status(required_books: Iterable[str], detected_books: Iterable[str]) -> dict:
    """Compare REQUIRED against DETECTED books (case-insensitive, order preserved).

    Returns required/detected/missing/extra lists, counts, a 0-100 percentage and
    a readiness flag. Extra books never count towards readiness.
    """
    required = list(dict.fromkeys(str(book).strip() for book in required_books))
    detected = list(dict.fromkeys(str(book).strip() for book in detected_books))
    required_lookup = {book.casefold(): book for book in required}
    packed_set = {book.casefold() for book in detected if book.casefold() in required_lookup}
    missing = [book for book in required if book.casefold() not in packed_set]
    extra = [book for book in detected if book.casefold() not in required_lookup]
    required_count = len(required)
    packed_count = len(packed_set)
    percentage = round(packed_count * 100 / required_count) if required_count else 100
    ready = not missing
    return {
        "required_books": required,
        "detected_books": detected,
        "missing_books": missing,
        "extra_books": extra,
        "packed_count": packed_count,
        "required_count": required_count,
        "percentage": percentage,
        "ready": ready,
        "status": "BAG READY" if ready else "BAG NOT READY",
    }
