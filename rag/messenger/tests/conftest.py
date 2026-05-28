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
import uuid

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402

from rag.config import settings as _settings  # noqa: E402
from rag.database.engine import get_async_session  # noqa: E402
from rag.main import app  # noqa: E402
from rag.messenger.redis_client import set_redis  # noqa: E402
from rag.messenger.routers import webhook as _webhook  # noqa: E402

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


# ---------------------------------------------------------------------------
# Phase 29.2 — every webhook path now depends on ``get_async_session`` so
# the inbound resolver can look up ``messenger_page_tenants``. Tests that
# don't care about tenancy get a no-op DB session + a default tenant
# resolver here so the suite keeps running without Postgres. The Phase 29.2
# tenancy test file overrides both fixtures with controllable doubles.
# ---------------------------------------------------------------------------

_DEFAULT_TEST_TENANT_ID = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
_DEFAULT_TEST_TENANT_SLUG = "hunter"


class _NullAsyncSession:
    """Minimal stand-in for AsyncSession — none of the messenger tests that
    use this fixture call any ORM method on the session; the resolver is
    monkeypatched out below."""

    async def __aenter__(self) -> "_NullAsyncSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _DefaultTenant:
    """Duck-typed Tenant row exposing the two fields the webhook reads."""

    def __init__(self) -> None:
        self.id = _DEFAULT_TEST_TENANT_ID
        self.slug = _DEFAULT_TEST_TENANT_SLUG


@pytest.fixture(autouse=True)
def stub_tenant_resolution(monkeypatch: pytest.MonkeyPatch):
    """Default every messenger test to ``page_id → Hunter tenant``.

    Phase 29.2 tenancy tests replace this binding via their own
    ``monkeypatch.setattr`` on ``rag.messenger.routers.webhook.resolve_tenant_for_page``.
    """

    async def _yield_null_session():
        yield _NullAsyncSession()

    async def _stub_resolve(_db: object, _page_id: str):
        return _DefaultTenant()

    app.dependency_overrides[get_async_session] = _yield_null_session
    monkeypatch.setattr(_webhook, "resolve_tenant_for_page", _stub_resolve)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_async_session, None)
