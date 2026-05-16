"""In-process async pub/sub event bus.

Fire-and-forget semantics: `publish()` returns immediately; subscribers run
concurrently as `asyncio.create_task`. Exceptions in one subscriber are logged
and do not block other subscribers.

Event registry (string constants — fixed for the SPA / API contract):

  - ingest.complete   {file, chunks, status, duration_ms}
  - ingest.failed     {file, error}
  - chat.complete     {session_id, question, tokens_in, tokens_out, latency_ms}
  - chat.feedback.up  {session_id, message_id, comment?}
  - chat.feedback.down{session_id, message_id, comment?}
  - chat.error        {session_id, error}
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]

EVENT_NAMES: tuple[str, ...] = (
    "ingest.complete",
    "ingest.failed",
    "chat.complete",
    "chat.feedback.up",
    "chat.feedback.down",
    "chat.error",
)


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._subs[event].append(handler)

    def unsubscribe_all(self, event: str | None = None) -> None:
        if event is None:
            self._subs.clear()
        else:
            self._subs.pop(event, None)

    def subscriber_count(self, event: str) -> int:
        return len(self._subs.get(event, []))

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        handlers = list(self._subs.get(event, []))
        for h in handlers:
            asyncio.create_task(_safe_run(h, event, payload))


async def _safe_run(handler: EventHandler, event: str, payload: dict[str, Any]) -> None:
    try:
        await handler(payload)
    except Exception as exc:  # noqa: BLE001 — top-level handler isolation
        logger.error("event handler failed event=%s err=%s", event, exc)


bus = EventBus()


def publish_sync(event: str, payload: dict[str, Any]) -> None:
    """Fire from sync code (e.g. ingest.py). Best-effort: silently no-op when
    no event loop is running (CLI ingest without an app context).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(bus.publish(event, payload))
        except RuntimeError:
            return
        return
    loop.create_task(bus.publish(event, payload))
