"""Demo/exhibition cards. A simulated scan is built here and then handed to the SAME
scan pipeline as a real card, labelled with source SIMULATION."""

from __future__ import annotations

import secrets


def uid_for_book(book: dict) -> str:
    """The book's real assigned UID if it has one, otherwise a reserved ``SIM<id>`` UID."""
    return book["rfid_uid"] or f"SIM{book['id']}"


def unknown_card_uid() -> str:
    """A UID that matches no book."""
    return "SIMX" + secrets.token_hex(3).upper()


def new_card_uid() -> str:
    """A fresh pretend card (used to demo 'scan to assign' without hardware)."""
    return "DEMO" + secrets.token_hex(4).upper()
