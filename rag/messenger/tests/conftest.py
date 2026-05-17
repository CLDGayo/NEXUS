"""Phase 2 / Phase 7 test bootstrap.

Sets a deterministic ``WEBHOOK_API_KEY`` and clears Langfuse keys so no
real network calls are issued during unit tests. Imports of
``rag.messenger.main`` elsewhere in the suite must occur AFTER pytest
imports this module.

Phase 7 — every webhook test now hits Redis (rate-limit + idempotency).
An autouse fixture swaps in a ``fakeredis.aioredis.FakeRedis`` so tests
don't need a running broker and each test gets fresh per-user state.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402

from rag.config import settings as _settings  # noqa: E402
from rag.messenger.redis_client import set_redis  # noqa: E402

# The Settings singleton is cached via ``functools.lru_cache``. If another
# test module imported ``rag.config`` before this conftest ran, the cached
# instance won't see our ``WEBHOOK_API_KEY`` env. Force it onto the live
# object so every test class in this file sees the auth as configured.
_settings.webhook_api_key = "test-key"
_settings.langfuse_public_key = None
_settings.langfuse_secret_key = None


@pytest.fixture(autouse=True)
def fake_redis():
    """Inject a fresh in-memory Redis for every messenger test."""

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis(client)
    try:
        yield client
    finally:
        set_redis(None)
