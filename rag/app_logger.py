"""Shared application logger — writes to data/app.log and keeps an in-memory ring buffer."""

import logging
import os
from collections import deque
from datetime import datetime, timezone

LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "app.log")
_ring: deque[dict] = deque(maxlen=200)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _ring.append({
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": self.format(record),
        })


def setup_logger() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger = logging.getLogger("nexus")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(fmt)

    ring_handler = _RingHandler()
    ring_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(ring_handler)
    return logger


def get_log_entries() -> list[dict]:
    return list(_ring)


logger = setup_logger()
