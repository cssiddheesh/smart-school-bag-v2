"""Application logging: console/journald plus a small rotating file."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    logger = logging.getLogger("ssb")
    if getattr(logger, "_ssb_configured", False):
        return
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False
    formatter = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:  # read-only SD card, wrong permissions, ...
        logger.warning("File logging disabled (%s). Logging to console only.", error)
    logger._ssb_configured = True  # type: ignore[attr-defined]
