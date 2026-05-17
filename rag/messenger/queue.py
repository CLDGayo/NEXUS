"""Redis-backed outbound retry queue.

Storage model:
    * Scheduled items live in a Redis sorted set
      ``settings.outbound_queue_key`` with score = next-attempt unix epoch.
      ``ZRANGEBYSCORE 0 now`` returns items currently due.
    * Permanently-failed items move to the list ``settings.outbound_dlq_key``
      via ``LPUSH`` (FIFO drain) — ops can inspect with ``LRANGE 0 -1``.
    * Each item is JSON-encoded; the queue handles serialization so callers
      pass ``QueuedItem`` dataclasses.

This module is intentionally thin: it does NOT perform sends; only
schedules retries and tracks state. The sender + worker are responsible
for the actual delivery loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as aioredis

from rag.config import settings

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedItem:
    """One outbound delivery awaiting (or scheduled for) retry."""

    correlation_id: str
    target_url: str
    payload: dict[str, Any]
    attempts: int = 0
    next_attempt_ts: int = 0
    first_failed_at: int | None = None
    last_error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "QueuedItem":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return cls(
            correlation_id=data["correlation_id"],
            target_url=data["target_url"],
            payload=data["payload"],
            attempts=int(data.get("attempts", 0)),
            next_attempt_ts=int(data.get("next_attempt_ts", 0)),
            first_failed_at=data.get("first_failed_at"),
            last_error=data.get("last_error"),
        )

    def with_attempt(self, *, error: str, now: int, backoff_seconds: int) -> "QueuedItem":
        return QueuedItem(
            correlation_id=self.correlation_id,
            target_url=self.target_url,
            payload=self.payload,
            attempts=self.attempts + 1,
            next_attempt_ts=now + backoff_seconds,
            first_failed_at=self.first_failed_at or now,
            last_error=error,
        )


def _now_epoch() -> int:
    return int(time.time())


class RedisOutboundQueue:
    """Async wrapper around the Redis sorted set + DLQ list."""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client
        self._queue_key = settings.outbound_queue_key
        self._dlq_key = settings.outbound_dlq_key

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    # ------------------------------------------------------------------
    # Enqueue / drain
    # ------------------------------------------------------------------

    async def enqueue(self, item: QueuedItem) -> None:
        """ZADD the item with score = next_attempt_ts (now if 0)."""

        score = item.next_attempt_ts if item.next_attempt_ts > 0 else _now_epoch()
        await self.client.zadd(self._queue_key, {item.to_json(): score})

    async def due_items(
        self, *, now: int | None = None, limit: int | None = None
    ) -> list[QueuedItem]:
        """Return + atomically remove items whose next_attempt_ts ≤ now.

        Atomic guarantee comes from the ZRANGE+ZREM pipeline transaction;
        another worker won't see the same item.
        """

        cutoff = now if now is not None else _now_epoch()
        cap = limit if limit is not None else settings.outbound_worker_batch_size

        async with self.client.pipeline(transaction=True) as pipe:
            await pipe.zrangebyscore(self._queue_key, 0, cutoff, start=0, num=cap)
            await pipe.zremrangebyscore(self._queue_key, 0, cutoff)
            raw_items, _removed = await pipe.execute()

        items: list[QueuedItem] = []
        for raw in raw_items or []:
            try:
                items.append(QueuedItem.from_json(raw))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                _log.warning("dropping malformed queue item: %s", exc)
        return items

    async def requeue(self, item: QueuedItem) -> None:
        """Reschedule an item after a failed attempt (called by the worker
        after computing the next backoff)."""

        await self.enqueue(item)

    async def dead_letter(self, item: QueuedItem) -> None:
        """Permanently fail. Item goes to a list, not a sorted set."""

        await self.client.lpush(self._dlq_key, item.to_json())
        _log.error(
            "outbound dead-lettered correlation_id=%s attempts=%d url=%s last_error=%s",
            item.correlation_id, item.attempts, item.target_url, item.last_error,
        )

    # ------------------------------------------------------------------
    # Observability helpers
    # ------------------------------------------------------------------

    async def depth(self) -> int:
        return int(await self.client.zcard(self._queue_key) or 0)

    async def dlq_depth(self) -> int:
        return int(await self.client.llen(self._dlq_key) or 0)


_queue_singleton: RedisOutboundQueue | None = None


def get_queue() -> RedisOutboundQueue:
    """Process-wide queue singleton."""

    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = RedisOutboundQueue()
    return _queue_singleton


def set_queue(queue: RedisOutboundQueue | None) -> None:
    """Test hook."""

    global _queue_singleton
    _queue_singleton = queue
