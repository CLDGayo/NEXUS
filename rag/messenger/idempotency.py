"""Redis-backed idempotency check for the messenger webhook.

n8n and Make retry failed POSTs aggressively. Without dedup, a slow ack
caused by a transient downstream blip would re-trigger the LangGraph
cortex (and re-charge LLM budget) for the same logical message.

Key shape: ``idemp:msgr:{user_id}:{correlation_id}:{body_hash}`` where
``body_hash`` is a sha256 prefix of the canonical Pydantic JSON
serialization of the inbound payload. Canonical JSON (rather than raw
request bytes) makes the key insensitive to upstream key-ordering or
whitespace shifts while still distinguishing genuinely different
payloads.

TTL: 24h by default. Comfortably exceeds n8n/Make retry windows; bounded
so Redis memory doesn't drift. Called inline from the webhook handler
(not as a FastAPI sub-dep) so it can see the already-parsed pydantic
body without re-reading the request stream.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rag.config import settings
from rag.messenger.redis_client import get_redis
from rag.messenger.schemas import InboundMessage


@dataclass(frozen=True)
class IdempotencyVerdict:
    """Result of the dedup check. ``duplicate=True`` means the handler
    must short-circuit with a ``duplicate`` ack instead of running the
    graph."""

    duplicate: bool
    key: str


def _key_for(payload: InboundMessage) -> str:
    canonical = payload.model_dump_json()
    body_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    correlation_id = payload.correlation_id or "noid"
    return f"idemp:msgr:{payload.user_id}:{correlation_id}:{body_hash}"


async def check_idempotency(payload: InboundMessage) -> IdempotencyVerdict:
    """Return verdict for ``payload``. Caller short-circuits on duplicate.

    Uses ``SET key 1 NX EX ttl`` — the atomic, single-round-trip primitive
    Redis exposes for this exact pattern. If the SET succeeds, this is the
    first time we've seen the request; if it fails (returns ``False``),
    another invocation already claimed the key.
    """

    key = _key_for(payload)
    redis = get_redis()
    set_ok = await redis.set(
        key,
        "1",
        nx=True,
        ex=settings.messenger_idempotency_ttl_s,
    )
    return IdempotencyVerdict(duplicate=not bool(set_ok), key=key)
