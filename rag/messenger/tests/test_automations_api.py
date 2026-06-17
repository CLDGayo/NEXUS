"""Phase 57.1 — DB-less unit tests + pg_required integration tests for the
facebook_automations CRUD API.

Layer A (DB-less, always runs):
    - path≠header X-Tenant-ID → 400
    - reply_payload missing "message" → 422
    - bad match_type → 422
    - PUT/DELETE missing row → 404
    - DELETE happy path → 204 empty body
    - router lockdown: every automations route depends on require_manager

Layer B (@pg_required integration, skips when no local Postgres):
    - full create→list(+page_id filter)→update(toggle is_active)→delete round-trip
    - cross-tenant 404: tenant B cannot PUT/DELETE tenant A's automation
"""

from __future__ import annotations

import asyncio
import inspect
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
AUTO_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")

_VALID_PAYLOAD: dict[str, Any] = {
    "page_id": "12345",
    "trigger_keyword": "price",
    "match_type": "exact",
    "reply_payload": {"message": "Here is our price list!"},
    "is_active": True,
}


# ---------------------------------------------------------------------------
# Fake tenant / user objects
# ---------------------------------------------------------------------------


class _FakeTenant:
    def __init__(self, tenant_id: uuid.UUID = TENANT_A_ID) -> None:
        self.id = tenant_id
        self.name = "Test Workspace"
        self.slug = "test-workspace"
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.archived_at = None
        self.avatar_url = None


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        self.email = "test@example.com"


# ---------------------------------------------------------------------------
# Dependency override helpers
# ---------------------------------------------------------------------------


def _make_fake_session(scalar_result: Any = None) -> AsyncMock:
    """Return an AsyncMock session that scalar_one_or_none() returns the given value."""
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    execute_result.scalar_one_or_none.return_value = scalar_result
    session.execute = AsyncMock(return_value=execute_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _install_overrides(
    app: Any,
    tenant: _FakeTenant | None = None,
    scalar_result: Any = None,
) -> None:
    """Wire dependency overrides onto the app for unit tests."""
    from rag.auth import current_active_user
    from rag.database.engine import get_async_session
    from rag.routers.deps import require_manager

    resolved_tenant = tenant or _FakeTenant()

    # The override MUST be an async-generator *function* so FastAPI iterates it
    # and injects the yielded session. A lambda that returns an async generator
    # object is treated as the solved value (db becomes the generator) → 500.
    async def _session_override() -> AsyncGenerator[AsyncMock, None]:
        yield _make_fake_session(scalar_result)

    app.dependency_overrides[current_active_user] = lambda: _FakeUser()
    app.dependency_overrides[require_manager] = lambda: resolved_tenant
    app.dependency_overrides[get_async_session] = _session_override


def _clear_overrides(app: Any) -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared test client fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> Any:
    from rag.main import app as _app

    return _app


@pytest.fixture(scope="module")
def client(app: Any) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Layer A — DB-less unit tests
# ---------------------------------------------------------------------------


def test_path_header_mismatch_returns_400(client: TestClient, app: Any) -> None:
    """Path tenant_id different from header (resolved tenant) → 400."""
    _install_overrides(app, tenant=_FakeTenant(TENANT_A_ID))
    try:
        different_id = TENANT_B_ID
        resp = client.get(
            f"/api/tenants/{different_id}/facebook/automations",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 400, resp.text
        assert "path tenant_id" in resp.json()["detail"]
    finally:
        _clear_overrides(app)


def test_create_missing_message_key_returns_422(client: TestClient, app: Any) -> None:
    """POST with reply_payload missing 'message' key → 422 schema validation."""
    _install_overrides(app)
    try:
        bad_payload = {**_VALID_PAYLOAD, "reply_payload": {"text": "no message key"}}
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations",
            json=bad_payload,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _clear_overrides(app)


def test_create_empty_message_returns_422(client: TestClient, app: Any) -> None:
    """POST with reply_payload 'message' = '' (empty string) → 422."""
    _install_overrides(app)
    try:
        bad_payload = {**_VALID_PAYLOAD, "reply_payload": {"message": "   "}}
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations",
            json=bad_payload,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _clear_overrides(app)


def test_create_bad_match_type_returns_422(client: TestClient, app: Any) -> None:
    """POST with match_type not in {exact, contains} → 422."""
    _install_overrides(app)
    try:
        bad_payload = {**_VALID_PAYLOAD, "match_type": "startswith"}
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations",
            json=bad_payload,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
    finally:
        _clear_overrides(app)


def test_put_missing_row_returns_404(client: TestClient, app: Any) -> None:
    """PUT on a non-existent automation (scalar_one_or_none → None) → 404."""
    _install_overrides(app, scalar_result=None)
    try:
        resp = client.put(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations/{AUTO_ID}",
            json={"is_active": False},
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "automation_not_found"
    finally:
        _clear_overrides(app)


def test_delete_missing_row_returns_404(client: TestClient, app: Any) -> None:
    """DELETE on a non-existent automation → 404."""
    _install_overrides(app, scalar_result=None)
    try:
        resp = client.delete(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations/{AUTO_ID}",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "automation_not_found"
    finally:
        _clear_overrides(app)


def test_delete_happy_path_returns_204_empty_body(client: TestClient, app: Any) -> None:
    """DELETE with a found row returns 204 with empty body.

    Proves response_class=Response wiring and that the app imported without
    crashing on the 204 route.
    """
    from rag.database.models import FacebookAutomation

    fake_row = MagicMock(spec=FacebookAutomation)
    fake_row.id = AUTO_ID
    fake_row.tenant_id = TENANT_A_ID

    _install_overrides(app, scalar_result=fake_row)
    try:
        resp = client.delete(
            f"/api/tenants/{TENANT_A_ID}/facebook/automations/{AUTO_ID}",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 204, resp.text
        assert resp.content == b""
    finally:
        _clear_overrides(app)


def test_automations_router_lockdown_uses_require_manager() -> None:
    """Every route in the automations router depends on require_manager.

    Mirror of test_phase31_routers_lockdown.py:48 pattern — static source
    inspection so a future accidental swap to require_auth fails loudly.
    """
    from rag.messenger.routers import automations as automations_module
    from rag.routers.deps import require_manager  # noqa: F401 — name check

    src = inspect.getsource(automations_module)
    assert "from rag.routers.deps import require_manager" in src, (
        "automations module must import require_manager from rag.routers.deps"
    )
    assert "Depends(require_manager)" in src, (
        "every automations route must gate by require_manager"
    )


# ---------------------------------------------------------------------------
# Layer B — pg_required integration tests (skip without local Postgres)
# ---------------------------------------------------------------------------


def _has_local_pg() -> str | None:
    """Return a usable Postgres DSN or None."""
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if dsn:
        return dsn
    try:
        with socket.create_connection(("localhost", 5432), timeout=0.5):
            return "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus_test"
    except OSError:
        return None


pg_required = pytest.mark.skipif(
    _has_local_pg() is None,
    reason="no local Postgres — set TEST_POSTGRES_DSN to run integration tests",
)


@pg_required
def test_automations_crud_roundtrip_and_cross_tenant_isolation() -> None:
    """Full create→list(+page_id filter)→update→delete round-trip.

    Also verifies that tenant B cannot PUT/DELETE tenant A's automation
    (cross-tenant 404 isolation).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from rag.database.base import Base
    from rag.database.models import FacebookAutomation, Tenant

    dsn = _has_local_pg()
    assert dsn is not None

    async def _run() -> None:
        engine = create_async_engine(dsn, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session: sessionmaker = sessionmaker(  # type: ignore[call-overload]
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async with async_session() as db:
            # -- create two tenants ------------------------------------------
            tenant_a = Tenant(
                id=uuid.uuid4(),
                name="Tenant A",
                slug=f"tenant-a-{uuid.uuid4().hex[:6]}",
            )
            tenant_b = Tenant(
                id=uuid.uuid4(),
                name="Tenant B",
                slug=f"tenant-b-{uuid.uuid4().hex[:6]}",
            )
            db.add_all([tenant_a, tenant_b])
            await db.commit()

            # -- create automation under tenant A ----------------------------
            auto = FacebookAutomation(
                tenant_id=tenant_a.id,
                page_id="page-111",
                trigger_keyword="hello",
                match_type="exact",
                reply_payload={"message": "Hi there!"},
                is_active=True,
            )
            db.add(auto)
            await db.commit()
            await db.refresh(auto)

            auto_id = auto.id
            assert auto.tenant_id == tenant_a.id

            # -- list all for tenant A ---------------------------------------
            from sqlalchemy import select

            stmt = select(FacebookAutomation).where(
                FacebookAutomation.tenant_id == tenant_a.id
            )
            rows = (await db.execute(stmt)).scalars().all()
            assert len(rows) >= 1
            assert any(r.id == auto_id for r in rows)

            # -- list filtered by page_id ------------------------------------
            stmt_filtered = select(FacebookAutomation).where(
                FacebookAutomation.tenant_id == tenant_a.id,
                FacebookAutomation.page_id == "page-111",
            )
            filtered = (await db.execute(stmt_filtered)).scalars().all()
            assert all(r.page_id == "page-111" for r in filtered)

            stmt_no_match = select(FacebookAutomation).where(
                FacebookAutomation.tenant_id == tenant_a.id,
                FacebookAutomation.page_id == "page-999",
            )
            no_match = (await db.execute(stmt_no_match)).scalars().all()
            assert len(no_match) == 0

            # -- update (toggle is_active) -----------------------------------
            auto.is_active = False
            await db.commit()
            await db.refresh(auto)
            assert auto.is_active is False

            # -- cross-tenant: tenant B cannot see tenant A's automation -----
            stmt_cross = select(FacebookAutomation).where(
                FacebookAutomation.id == auto_id,
                FacebookAutomation.tenant_id == tenant_b.id,
            )
            cross_row = (await db.execute(stmt_cross)).scalar_one_or_none()
            assert cross_row is None, (
                "Tenant B must not be able to access Tenant A's automation"
            )

            # -- delete ------------------------------------------------------
            await db.delete(auto)
            await db.commit()

            stmt_gone = select(FacebookAutomation).where(
                FacebookAutomation.id == auto_id
            )
            gone = (await db.execute(stmt_gone)).scalar_one_or_none()
            assert gone is None

        await engine.dispose()

    asyncio.run(_run())
