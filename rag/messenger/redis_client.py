"""Shared async Redis client for messenger security paths.

Idempotency and rate-limit dependencies live in the request hot path and
must not pay the cost of opening a new connection per request. This
module owns a process-wide ``redis.asyncio.Redis`` instance built from
``settings.redis_url``.

A separate ``RedisOutboundQueue`` in ``rag.messenger.queue`` maintains
its own pool for the worker's blocking-style drain loop. Two clients,
two pools — deliberate isolation so a stuck queue drain can't starve
the inbound auth path.

Test hook: :func:`set_redis` swaps in a ``fakeredis.aioredis.FakeRedis``.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from rag.config import settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the process-wide async Redis client. Lazy-instantiated."""

    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_redis(client: aioredis.Redis | None) -> None:
    """Test hook — inject a fake or reset the singleton."""

    global _client
    _client = client
