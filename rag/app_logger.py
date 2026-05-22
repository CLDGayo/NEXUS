"""Shared application logger.

Phase 25.1 — configures the **root** logger so every module that uses
``logging.getLogger(__name__)`` lands records in both ``data/app.log`` and
stdout (``docker logs``). The legacy ``logger = logging.getLogger("nexus")``
call site keeps working unchanged.

Handlers are tagged with a ``_nexus`` attribute so repeated calls to
``setup_logger()`` (module reload, test fixtures, second uvicorn worker)
never attach duplicate handlers.
"""

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


def _has_nexus_handler(root: logging.Logger, marker: str) -> bool:
    return any(getattr(h, "_nexus", None) == marker for h in root.handlers)


def setup_logger() -> logging.Logger:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    root = logging.getLogger()
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    if not _has_nexus_handler(root, "file"):
        file_handler = logging.FileHandler(LOG_PATH)
        file_handler.setFormatter(fmt)
        file_handler._nexus = "file"  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    if not _has_nexus_handler(root, "stream"):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        stream_handler._nexus = "stream"  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    if not _has_nexus_handler(root, "ring"):
        ring_handler = _RingHandler()
        ring_handler.setFormatter(fmt)
        ring_handler._nexus = "ring"  # type: ignore[attr-defined]
        root.addHandler(ring_handler)

    nexus = logging.getLogger("nexus")
    nexus.setLevel(logging.INFO)
    # The "nexus" logger used to own its own FileHandler. Now we rely on
    # propagation to root. Strip any pre-existing handlers so a single
    # log call doesn't write twice.
    for handler in list(nexus.handlers):
        nexus.removeHandler(handler)
    nexus.propagate = True
    return nexus


def get_log_entries() -> list[dict]:
    return list(_ring)


logger = setup_logger()
