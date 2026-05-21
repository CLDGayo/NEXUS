"""Redis-backed idempotency + per-thread serialization for the messenger surface.

Two distinct hot-path needs share this module:

1. **Idempotency**. Meta (Phase 12 direct) and n8n / Make (Phase 6 broker)
   both retry failed POSTs aggressively. Without dedup, a slow ack would
   re-trigger the LangGraph cortex (and re-charge LLM budget) for the
   same logical message.

   - :func:`check_idempotency` keys off the Pydantic body hash. Used by
     the broker path, where the upstream supplies a stable
     ``correlation_id`` and we trust the canonical payload bytes.
   - :func:`claim_content_idempotency` keys off the *semantic content*
     of the inbound (``sender + page + normalized text + attachment urls
     + minute_bucket``) so a Meta retry with a brand-new ``mid`` still
     dedupes. Used by the direct path, where the upstream ``mid`` is
     unreliable across retries.

2. **Per-thread serialization**. When two events for the same user
   arrive near-simultaneously, two background tasks would race on the
   same LangGraph checkpointer thread. :func:`acquire_thread_lock`
   /:func:`release_thread_lock` wrap Redis ``SET NX EX`` to serialize
   them: the first task acquires, peers drop with
   ``messenger.event.dropped_locked``.

Both primitives use ``SET key 1 NX EX ttl`` — the single-round-trip
atomic claim Redis exposes for this exact pattern. TTLs are bounded so
Redis memory never drifts; lock TTL is short so a crashed task can't
indefinitely block its thread.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rag.config import settings
from rag.messenger.redis_client import get_redis
from rag.messenger.schemas import InboundMessage

# Lock TTL — long enough to cover a normal graph run + outbound dispatch,
# short enough that a crashed task can't wedge a user's thread forever.
THREAD_LOCK_TTL_S = 60

# Content-claim TTL — well past Meta's webhook retry window (≈ 1 min)
# without keeping ghost keys forever.
CONTENT_CLAIM_TTL_S = 600

# Bucket size for collapsing rapid-fire retries of the same logical
# message. 60 s is the same order as Meta's retry cadence.
CONTENT_CLAIM_BUCKET_S = 60

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class IdempotencyVerdict:
    """Result of the dedup check. ``duplicate=True`` means the handler
    must short-circuit instead of running the graph."""

    duplicate: bool
    key: str


@dataclass(frozen=True)
class LockVerdict:
    """Result of acquiring a per-thread lock. ``acquired=False`` means
    a peer is already running the graph for this thread; drop the event."""

    acquired: bool
    key: str


# ---------------------------------------------------------------------------
# Body-hash idempotency (broker path)
# ---------------------------------------------------------------------------

def _key_for(payload: InboundMessage) -> str:
    canonical = payload.model_dump_json()
    body_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    correlation_id = payload.correlation_id or "noid"
    return f"idemp:msgr:{payload.user_id}:{correlation_id}:{body_hash}"


async def check_idempotency(payload: InboundMessage) -> IdempotencyVerdict:
    """Body-hash dedup for the broker path. Caller short-circuits on duplicate."""

    key = _key_for(payload)
    redis = get_redis()
    set_ok = await redis.set(
        key,
        "1",
        nx=True,
        ex=settings.messenger_idempotency_ttl_s,
    )
    return IdempotencyVerdict(duplicate=not bool(set_ok), key=key)


# ---------------------------------------------------------------------------
# Content-keyed idempotency (Meta direct path)
# ---------------------------------------------------------------------------

def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def _attachment_urls(payload: InboundMessage) -> str:
    if not payload.attachments:
        return ""
    urls = sorted(
        str(att.get("url", "")) for att in payload.attachments if isinstance(att, dict)
    )
    return "|".join(urls)


def content_idempotency_key(payload: InboundMessage) -> str:
    """Derive a content-stable dedup key for one inbound message.

    Independent of the upstream ``mid`` / ``correlation_id`` so a Meta
    retry with a fresh mid still collides with the original. Bucketed
    into ``CONTENT_CLAIM_BUCKET_S``-second windows so a user genuinely
    re-sending the exact same text a day later is treated as a new turn.
    """

    page_id = payload.page_id or ""
    bucket = int(payload.timestamp) // CONTENT_CLAIM_BUCKET_S
    raw = "|".join(
        (
            payload.user_id,
            page_id,
            _normalize_text(payload.message_text),
            _attachment_urls(payload),
            str(bucket),
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"idemp:msgr-content:{payload.user_id}:{digest}"


async def claim_content_idempotency(payload: InboundMessage) -> IdempotencyVerdict:
    """Atomic content-keyed claim. ``duplicate=True`` if another envelope
    already claimed the slot — caller must NOT schedule a task.

    Falls back to ``duplicate=False`` if Redis is unavailable so a Redis
    outage degrades gracefully (better double-reply than no reply at all).
    """

    key = content_idempotency_key(payload)
    redis = get_redis()
    try:
        set_ok = await redis.set(key, "1", nx=True, ex=CONTENT_CLAIM_TTL_S)
    except Exception:  # noqa: BLE001 — Redis flake must not break the surface
        return IdempotencyVerdict(duplicate=False, key=key)
    return IdempotencyVerdict(duplicate=not bool(set_ok), key=key)


# ---------------------------------------------------------------------------
# Per-thread serialization lock
# ---------------------------------------------------------------------------

def thread_lock_key(thread_key: str) -> str:
    return f"messenger:lock:{thread_key}"


async def acquire_thread_lock(thread_key: str) -> LockVerdict:
    """Atomic SET NX EX. ``acquired=False`` means a peer is mid-flight."""

    key = thread_lock_key(thread_key)
    redis = get_redis()
    try:
        set_ok = await redis.set(key, "1", nx=True, ex=THREAD_LOCK_TTL_S)
    except Exception:  # noqa: BLE001 — Redis flake must not block the surface
        return LockVerdict(acquired=True, key=key)
    return LockVerdict(acquired=bool(set_ok), key=key)


async def release_thread_lock(thread_key: str) -> None:
    """Best-effort lock release. Silent on Redis errors — the TTL is the
    backstop, so a missed release just delays the next event for the
    user by at most ``THREAD_LOCK_TTL_S`` seconds."""

    key = thread_lock_key(thread_key)
    redis = get_redis()
    try:
        await redis.delete(key)
    except Exception:  # noqa: BLE001
        return
