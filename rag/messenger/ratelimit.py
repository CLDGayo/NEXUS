"""Per-user sliding-window rate limiter for the messenger webhook.

Caps each Facebook user ID to ``MESSENGER_RATE_LIMIT_PER_MIN`` (default
20) inbound messages per rolling 60-second window. Implemented as a
Redis sorted set:

    * ZADD timestamp-keyed member into ``rl:msgr:{user_id}``.
    * ZREMRANGEBYSCORE evicts entries older than the window edge.
    * ZCARD counts surviving entries; if > limit, raises.
    * EXPIRE 90s caps memory growth for inactive users.

The four ops run in a single pipeline — one round trip, atomic enough
for rate-limit purposes (a tiny race at the edge of the window is
benign).

Per-IP limiting is intentionally absent: Facebook pages share egress
IPs, so IP-level caps would friendly-fire across legitimate tenants.

Called inline from the webhook handler — see :mod:`rag.messenger.idempotency`
for the rationale on not using FastAPI sub-deps with Body params.
"""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import HTTPException, status

from rag.config import settings
from rag.messenger.redis_client import get_redis
from rag.messenger.schemas import InboundMessage


_WINDOW_MS = 60_000


async def enforce_rate_limit(payload: InboundMessage) -> None:
    """Raise ``HTTPException(429)`` past the per-minute cap. No-op when
    ``settings.messenger_rate_limit_per_min`` is 0 or below."""

    max_per_min = settings.messenger_rate_limit_per_min
    if max_per_min <= 0:
        return

    redis = get_redis()
    now_ms = int(time.time() * 1000)
    key = f"rl:msgr:{payload.user_id}"
    member = f"{now_ms}-{uuid4().hex[:8]}"

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - _WINDOW_MS)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, 90)
    results = await pipe.execute()
    count = int(results[2])

    if count > max_per_min:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
            headers={"Retry-After": "60"},
        )
