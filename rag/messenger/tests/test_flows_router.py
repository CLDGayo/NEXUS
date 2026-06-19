"""Phase 58.1 — DB-less unit tests + pg_required integration tests for the
nexus_flows CRUD API.

Layer A (DB-less, always runs):
    - path≠header X-Tenant-ID → 400
    - FlowStateModel validator: exactly-one-trigger (0 or 2 triggers → 422)
    - PUT/DELETE missing row → 404 (flow_not_found)
    - DELETE happy path → 204 empty body (proves response_class=Response wiring
      + that the app imported without crashing on the 204 route)
    - router lockdown: every flows route depends on require_manager

Layer B (@pg_required integration, skips when no local Postgres):
    - full create→list→update(toggle is_active)→delete round-trip
    - cross-tenant 404: tenant B cannot see tenant A's flow

Mirrors test_automations_api.py (Phase 57.1). The session override is an
async-generator *function* (not a lambda returning a generator) — a lambda that
returns an async-gen object is treated as the solved value (db becomes the
generator) → silent 500.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
FLOW_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")


def _node(node_id: str, node_type: str) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": {"x": 0.0, "y": 0.0}, "data": {}}


def _flow_state(node_types: list[str]) -> dict[str, Any]:
    """Build a flow_state dict with the given node types (no edges)."""
    return {
        "nodes": [_node(f"n{i}", t) for i, t in enumerate(node_types)],
        "edges": [],
        "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
    }


_VALID_PAYLOAD: dict[str, Any] = {
    "page_id": "12345",
    "name": "Welcome flow",
    "flow_state": _flow_state(["commentTrigger", "sendMessage"]),
    "is_active": False,
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


def _make_fake_session(scalar_result: Any = None) -> Any:
    """AsyncMock session whose scalar_one_or_none() returns the given value."""
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    execute_result.scalar_one_or_none.return_value = scalar_result
    session.execute = AsyncMock(return_value=execute_result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    async def _refresh(obj: Any, *a: Any, **k: Any) -> None:
        # Simulate the DB filling server-side defaults so NexusFlowRead can
        # validate the freshly-created/updated row on happy paths.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    session.refresh = AsyncMock(side_effect=_refresh)
    session.delete = AsyncMock()
    return session


def _install_overrides(
    app: Any,
    tenant: _FakeTenant | None = None,
    scalar_result: Any = None,
) -> None:
    from rag.auth import current_active_user
    from rag.database.engine import get_async_session
    from rag.routers.deps import require_manager

    resolved_tenant = tenant or _FakeTenant()

    # MUST be an async-generator *function* (see module docstring / gotcha 3).
    async def _session_override() -> AsyncGenerator[Any, None]:
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
# FlowStateModel validator — pure unit (no HTTP)
# ---------------------------------------------------------------------------


def test_flowstate_accepts_empty_nodes() -> None:
    """Validator removed — empty/partial drafts must construct fine."""
    from rag.messenger.routers.flows import FlowStateModel

    fs = FlowStateModel(nodes=[], edges=[])
    assert fs.nodes == []


def test_flowstate_accepts_arbitrary_trigger_counts() -> None:
    """Trigger-count is enforced at the router (when active), not on the model."""
    from rag.messenger.routers.flows import FlowStateModel

    fs0 = FlowStateModel(**_flow_state(["sendMessage", "condition"]))  # 0 triggers
    fs2 = FlowStateModel(**_flow_state(["commentTrigger", "dmTrigger"]))  # 2 triggers
    assert len(fs0.nodes) == 2 and len(fs2.nodes) == 2


# ---------------------------------------------------------------------------
# Layer A — DB-less HTTP tests
# ---------------------------------------------------------------------------


def test_path_header_mismatch_returns_400(client: TestClient, app: Any) -> None:
    _install_overrides(app, tenant=_FakeTenant(TENANT_A_ID))
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_B_ID}/facebook/flows",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 400, resp.text
        assert "path tenant_id" in resp.json()["detail"]
    finally:
        _clear_overrides(app)


def test_create_inactive_empty_draft_returns_201(client: TestClient, app: Any) -> None:
    """An inactive draft with an empty canvas saves successfully (201)."""
    _install_overrides(app)
    try:
        draft = {
            "page_id": "12345",
            "name": "Draft flow",
            "flow_state": {"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}},
            "is_active": False,
        }
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows",
            json=draft,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["is_active"] is False
        assert body["flow_state"]["nodes"] == []
    finally:
        _clear_overrides(app)


def test_create_active_empty_returns_422(client: TestClient, app: Any) -> None:
    """Activating an empty flow (no trigger) is rejected with 422."""
    _install_overrides(app)
    try:
        bad = {
            "page_id": "12345",
            "name": "Bad active flow",
            "flow_state": {"nodes": [], "edges": []},
            "is_active": True,
        }
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows",
            json=bad,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "active_flow_requires_exactly_one_trigger"
    finally:
        _clear_overrides(app)


def test_create_active_two_triggers_returns_422(client: TestClient, app: Any) -> None:
    _install_overrides(app)
    try:
        bad = {
            "page_id": "12345",
            "name": "Two triggers",
            "flow_state": _flow_state(["commentTrigger", "dmTrigger"]),
            "is_active": True,
        }
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows",
            json=bad,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "active_flow_requires_exactly_one_trigger"
    finally:
        _clear_overrides(app)


def test_create_active_single_trigger_returns_201(client: TestClient, app: Any) -> None:
    """A valid active flow (exactly one trigger) is created (201)."""
    _install_overrides(app)
    try:
        good = {**_VALID_PAYLOAD, "is_active": True}  # commentTrigger + sendMessage
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows",
            json=good,
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["is_active"] is True
    finally:
        _clear_overrides(app)


def test_put_missing_row_returns_404(client: TestClient, app: Any) -> None:
    _install_overrides(app, scalar_result=None)
    try:
        resp = client.put(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}",
            json={"is_active": False},
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "flow_not_found"
    finally:
        _clear_overrides(app)


def test_update_activate_empty_flow_returns_422(client: TestClient, app: Any) -> None:
    """PUT is_active=True on a flow whose stored canvas is empty → 422."""
    from unittest.mock import MagicMock

    from rag.database.models import NexusFlow

    row = MagicMock(spec=NexusFlow)
    row.id = FLOW_ID
    row.tenant_id = TENANT_A_ID
    row.is_active = False
    row.flow_state = {"nodes": [], "edges": []}

    _install_overrides(app, scalar_result=row)
    try:
        resp = client.put(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}",
            json={"is_active": True},
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "active_flow_requires_exactly_one_trigger"
    finally:
        _clear_overrides(app)


def test_delete_missing_row_returns_404(client: TestClient, app: Any) -> None:
    _install_overrides(app, scalar_result=None)
    try:
        resp = client.delete(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "flow_not_found"
    finally:
        _clear_overrides(app)


def test_delete_happy_path_returns_204_empty_body(client: TestClient, app: Any) -> None:
    from unittest.mock import MagicMock

    from rag.database.models import NexusFlow

    fake_row = MagicMock(spec=NexusFlow)
    fake_row.id = FLOW_ID
    fake_row.tenant_id = TENANT_A_ID

    _install_overrides(app, scalar_result=fake_row)
    try:
        resp = client.delete(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}",
            headers={"X-Tenant-ID": str(TENANT_A_ID)},
        )
        assert resp.status_code == 204, resp.text
        assert resp.content == b""
    finally:
        _clear_overrides(app)


def test_flows_router_lockdown_uses_require_manager() -> None:
    """Every route in the flows router gates by require_manager."""
    from rag.messenger.routers import flows as flows_module
    from rag.routers.deps import require_manager  # noqa: F401 — name check

    src = inspect.getsource(flows_module)
    assert "from rag.routers.deps import require_manager" in src, (
        "flows module must import require_manager from rag.routers.deps"
    )
    assert "Depends(require_manager)" in src, (
        "every flows route must gate by require_manager"
    )


# ---------------------------------------------------------------------------
# Phase 58.4a — analytics endpoints (DB-less, sequenced execute results)
# ---------------------------------------------------------------------------


class _SeqResult:
    """Execute-result double exposing both .all() and .scalar_one_or_none()."""

    def __init__(self, *, all_rows: Any = None, scalar: Any = None) -> None:
        self._all = all_rows or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return self._all

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _install_analytics_overrides(app: Any, results: list[_SeqResult]) -> None:
    """Override the session so each db.execute() returns the next _SeqResult."""
    from unittest.mock import AsyncMock, MagicMock

    from rag.auth import current_active_user
    from rag.database.engine import get_async_session
    from rag.routers.deps import require_manager

    seq = list(results)
    calls = {"i": 0}

    async def _execute(_stmt: Any) -> Any:
        i = calls["i"]
        calls["i"] += 1
        return seq[i] if i < len(seq) else _SeqResult()

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.add = MagicMock()
    session.commit = AsyncMock()

    async def _session_override() -> AsyncGenerator[Any, None]:
        yield session

    app.dependency_overrides[current_active_user] = lambda: _FakeUser()
    app.dependency_overrides[require_manager] = lambda: _FakeTenant()
    app.dependency_overrides[get_async_session] = _session_override


def test_analytics_summary_aggregates_per_flow(client: TestClient, app: Any) -> None:
    f1 = uuid.UUID("11111111-0000-0000-0000-000000000001")
    f2 = uuid.UUID("22222222-0000-0000-0000-000000000002")
    # (flow_id, status, count) rows — F1: 3 completed + 1 failed; F2: 1 active.
    rows = [
        (f1, "completed", 3),
        (f1, "failed", 1),
        (f2, "active", 1),
    ]
    _install_analytics_overrides(app, [_SeqResult(all_rows=rows)])
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/analytics/summary"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window_days"] == 7
        by_id = {row["flow_id"]: row for row in body["flows"]}
        assert by_id[str(f1)] == {
            "flow_id": str(f1),
            "total": 4,
            "completed": 3,
            "failed": 1,
            "success_rate": 0.75,
        }
        # In-flight-only flow: no terminal runs → 0.0 success rate.
        assert by_id[str(f2)]["total"] == 1
        assert by_id[str(f2)]["success_rate"] == 0.0
    finally:
        _clear_overrides(app)


def test_flow_analytics_404_when_flow_not_owned(
    client: TestClient, app: Any
) -> None:
    # 1st execute = ownership check → scalar None → 404 (never reaches the
    # run-aggregation query).
    _install_analytics_overrides(app, [_SeqResult(scalar=None)])
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}/analytics"
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "flow_not_found"
    finally:
        _clear_overrides(app)


def test_flow_analytics_node_aggregation(client: TestClient, app: Any) -> None:
    # 1st execute = ownership (returns the flow id), 2nd = run rows.
    run_rows = [
        ("completed", ["n1", "n2"], None),
        ("failed", ["n1", "n3"], "n3"),
    ]
    _install_analytics_overrides(
        app,
        [_SeqResult(scalar=FLOW_ID), _SeqResult(all_rows=run_rows)],
    )
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_A_ID}/facebook/flows/{FLOW_ID}/analytics"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["runs"] == {
            "total": 2,
            "active": 0,
            "waiting": 0,
            "completed": 1,
            "failed": 1,
            "success_rate": 0.5,
        }
        nodes = {n["node_id"]: n for n in body["nodes"]}
        assert nodes["n1"] == {"node_id": "n1", "visits": 2, "failures": 0}
        assert nodes["n2"] == {"node_id": "n2", "visits": 1, "failures": 0}
        assert nodes["n3"] == {"node_id": "n3", "visits": 1, "failures": 1}
    finally:
        _clear_overrides(app)


# ---------------------------------------------------------------------------
# Layer B — pg_required integration tests
# ---------------------------------------------------------------------------


def _has_local_pg() -> str | None:
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
def test_flows_crud_roundtrip_and_cross_tenant_isolation() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from rag.database.base import Base
    from rag.database.models import NexusFlow, Tenant

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
            tenant_a = Tenant(id=uuid.uuid4(), name="Tenant A", slug=f"a-{uuid.uuid4().hex[:6]}")
            tenant_b = Tenant(id=uuid.uuid4(), name="Tenant B", slug=f"b-{uuid.uuid4().hex[:6]}")
            db.add_all([tenant_a, tenant_b])
            await db.commit()

            flow = NexusFlow(
                tenant_id=tenant_a.id,
                page_id="page-111",
                name="Welcome",
                flow_state=_flow_state(["commentTrigger", "sendMessage"]),
                is_active=True,
            )
            db.add(flow)
            await db.commit()
            await db.refresh(flow)
            flow_id = flow.id
            assert flow.tenant_id == tenant_a.id

            rows = (
                await db.execute(
                    select(NexusFlow).where(NexusFlow.tenant_id == tenant_a.id)
                )
            ).scalars().all()
            assert any(r.id == flow_id for r in rows)

            flow.is_active = False
            await db.commit()
            await db.refresh(flow)
            assert flow.is_active is False

            cross = (
                await db.execute(
                    select(NexusFlow).where(
                        NexusFlow.id == flow_id,
                        NexusFlow.tenant_id == tenant_b.id,
                    )
                )
            ).scalar_one_or_none()
            assert cross is None, "Tenant B must not access Tenant A's flow"

            await db.delete(flow)
            await db.commit()
            gone = (
                await db.execute(select(NexusFlow).where(NexusFlow.id == flow_id))
            ).scalar_one_or_none()
            assert gone is None

        await engine.dispose()

    asyncio.run(_run())
