"""Phase 66 — DB-less unit tests for the Audience Broadcasting API.

Two layers:

Pure predicate (no HTTP, no DB):
    - ``_within_messaging_window`` — the single source of truth for Meta's 24h
      standard messaging window. None → ineligible, boundary at exactly 24h,
      inside/outside, naive-tz coercion, future timestamps.

Layer A (DB-less HTTP, mocked session + manager override):
    - path≠header X-Tenant-ID → 400 (reach + fire)
    - router lockdown: every broadcasts route depends on require_manager
    - flow not found → 404
    - reach splits matched contacts by the 24h window (the headline compliance
      test): mixed last_interaction_at → only in-window contacts counted eligible
    - fire enqueues ONLY in-window contacts and skips the rest

The session override is an async-generator *function* (not a lambda returning a
generator) — see test_flows_router.py gotcha 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from rag.messenger.routers.broadcasts import (
    MESSAGING_WINDOW_HOURS,
    _within_messaging_window,
)

TENANT_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
FLOW_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
PAGE_ID = "1234567890"


# ---------------------------------------------------------------------------
# Pure predicate — the compliance gate
# ---------------------------------------------------------------------------


def test_window_none_is_never_eligible() -> None:
    """A contact who never messaged the page (NULL) is always out of window."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    assert _within_messaging_window(None, now) is False


def test_window_inside_is_eligible() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    assert _within_messaging_window(one_hour_ago, now) is True


def test_window_just_outside_is_skipped() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    just_over = now - timedelta(hours=MESSAGING_WINDOW_HOURS, seconds=1)
    assert _within_messaging_window(just_over, now) is False


def test_window_exact_boundary_is_eligible() -> None:
    """Exactly 24h ago sits on the inclusive ``>=`` edge → still eligible."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    exactly = now - timedelta(hours=MESSAGING_WINDOW_HOURS)
    assert _within_messaging_window(exactly, now) is True


def test_window_naive_timestamp_coerced_utc() -> None:
    """Defensive: a naive datetime is treated as UTC, not crashed on."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    naive_recent = datetime(2026, 6, 22, 11, 0)  # no tzinfo
    assert _within_messaging_window(naive_recent, now) is True


# ---------------------------------------------------------------------------
# Fakes / overrides
# ---------------------------------------------------------------------------


class _FakeTenant:
    def __init__(self, tenant_id: uuid.UUID = TENANT_A_ID) -> None:
        self.id = tenant_id
        self.name = "Test Workspace"
        self.slug = "test-workspace"
        self.archived_at = None


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        self.email = "test@example.com"


class _FakeFlow:
    def __init__(self) -> None:
        self.id = FLOW_ID
        self.tenant_id = TENANT_A_ID
        self.page_id = PAGE_ID


def _make_session(
    flow: Any = None, contact_rows: list[tuple[str, Any]] | None = None
) -> Any:
    """Session whose two execute() calls return (flow), then (contact rows).

    Call 1 = ``_load_flow_or_404`` → ``.scalar_one_or_none()`` = ``flow``.
    Call 2 = matched-contacts query → ``.all()`` = ``contact_rows``.
    """
    flow_result = MagicMock()
    flow_result.scalar_one_or_none.return_value = flow

    contacts_result = MagicMock()
    contacts_result.all.return_value = contact_rows or []

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[flow_result, contacts_result])
    return session


def _install_overrides(
    app: Any,
    tenant: _FakeTenant | None = None,
    flow: Any = None,
    contact_rows: list[tuple[str, Any]] | None = None,
) -> None:
    from rag.auth import current_active_user
    from rag.database.engine import get_async_session
    from rag.routers.deps import require_manager

    resolved_tenant = tenant or _FakeTenant()
    session = _make_session(flow, contact_rows)

    async def _session_override() -> AsyncGenerator[Any, None]:
        yield session

    app.dependency_overrides[current_active_user] = lambda: _FakeUser()
    app.dependency_overrides[require_manager] = lambda: resolved_tenant
    app.dependency_overrides[get_async_session] = _session_override


def _clear_overrides(app: Any) -> None:
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def app() -> Any:
    from rag.main import app as _app

    return _app


@pytest.fixture(scope="module")
def client(app: Any) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _hdr() -> dict[str, str]:
    return {"X-Tenant-ID": str(TENANT_A_ID)}


# ---------------------------------------------------------------------------
# Layer A — DB-less HTTP
# ---------------------------------------------------------------------------


def test_reach_path_header_mismatch_returns_400(client: TestClient, app: Any) -> None:
    _install_overrides(app, tenant=_FakeTenant(TENANT_A_ID), flow=_FakeFlow())
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_B_ID}/facebook/broadcasts/reach",
            json={"flow_id": str(FLOW_ID), "filters": {}},
            headers=_hdr(),
        )
        assert resp.status_code == 400, resp.text
        assert "path tenant_id" in resp.json()["detail"]
    finally:
        _clear_overrides(app)


def test_fire_path_header_mismatch_returns_400(client: TestClient, app: Any) -> None:
    _install_overrides(app, tenant=_FakeTenant(TENANT_A_ID), flow=_FakeFlow())
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_B_ID}/facebook/broadcasts/fire",
            json={"flow_id": str(FLOW_ID), "filters": {}},
            headers=_hdr(),
        )
        assert resp.status_code == 400, resp.text
    finally:
        _clear_overrides(app)


def test_reach_flow_not_found_returns_404(client: TestClient, app: Any) -> None:
    _install_overrides(app, flow=None)  # flow query → None
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/broadcasts/reach",
            json={"flow_id": str(FLOW_ID), "filters": {}},
            headers=_hdr(),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "flow_not_found"
    finally:
        _clear_overrides(app)


def test_reach_splits_contacts_by_24h_window(client: TestClient, app: Any) -> None:
    """Headline compliance test: only in-window contacts are counted eligible."""
    now = datetime.now(timezone.utc)
    rows = [
        ("sender_in_1h", now - timedelta(hours=1)),  # eligible
        ("sender_in_23h", now - timedelta(hours=23)),  # eligible
        ("sender_out_25h", now - timedelta(hours=25)),  # skipped
        ("sender_never", None),  # skipped
    ]
    _install_overrides(app, flow=_FakeFlow(), contact_rows=rows)
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/broadcasts/reach",
            json={"flow_id": str(FLOW_ID), "filters": {"tag": "vip"}},
            headers=_hdr(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_matched"] == 4
        assert body["eligible"] == 2
        assert body["skipped_outside_window"] == 2
        assert body["window_hours"] == 24
    finally:
        _clear_overrides(app)


def test_fire_enqueues_only_in_window_contacts(
    client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fire must enqueue ONLY in-window senders and skip the rest."""
    now = datetime.now(timezone.utc)
    rows = [
        ("sender_in", now - timedelta(hours=2)),  # eligible
        ("sender_out", now - timedelta(hours=48)),  # skipped
        ("sender_never", None),  # skipped
    ]

    calls: list[dict[str, Any]] = []

    async def _fake_enqueue(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "rag.messenger.routers.broadcasts.enqueue_broadcast_job", _fake_enqueue
    )

    _install_overrides(app, flow=_FakeFlow(), contact_rows=rows)
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/broadcasts/fire",
            json={"flow_id": str(FLOW_ID), "filters": {}},
            headers=_hdr(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_matched"] == 3
        assert body["queued"] == 1
        assert body["skipped_outside_window"] == 2

        # Exactly one job, for the in-window sender only.
        assert len(calls) == 1
        assert calls[0]["sender_id"] == "sender_in"
        assert calls[0]["flow_id"] == str(FLOW_ID)
        assert calls[0]["page_id"] == PAGE_ID
    finally:
        _clear_overrides(app)


def test_every_broadcasts_route_requires_manager(app: Any) -> None:
    """Router lockdown: no broadcasts route is reachable without require_manager."""
    from rag.routers.deps import require_manager

    broadcast_routes = [
        r
        for r in app.routes
        if getattr(r, "path", "").endswith(("/broadcasts/reach", "/broadcasts/fire"))
    ]
    assert broadcast_routes, "no broadcast routes registered"
    for route in broadcast_routes:
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_manager in dep_calls, f"{route.path} missing require_manager"
