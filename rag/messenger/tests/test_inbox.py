"""Phase 67 — Live Chat Inbox & Human Handoff tests.

Three layers, all DB-less:

Pure predicate (no I/O):
    - ``flow_engine._pause_active`` — None/past/future/naive-tz coercion.

Engine handoff (the headline test):
    - a thread with ``bot_paused_until`` in the future blocks the NEXUS Flow
      engine from replying: ``resume_flow_for_dm`` short-circuits BEFORE touching
      the DB or sending, and never calls ``_traverse``.

Inbox router (DB-less HTTP, mocked session + manager override):
    - path≠header X-Tenant-ID → 400
    - contact not found → 404 (messages + send)
    - router lockdown: every inbox route depends on require_manager
    - manual send dispatches via Graph API, logs an outbound row, and pauses the
      bot 24h (both the DB stamp and the Redis HITL key).

The session override is an async-generator *function* (not a lambda returning a
generator) — see test_flows_router.py gotcha 3 / test_broadcasts_router.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from rag.messenger import flow_engine
from rag.messenger.flow_engine import _pause_active
from rag.messenger.routers.inbox import HANDOFF_PAUSE_HOURS

HANDOFF_PAUSE_SECONDS = HANDOFF_PAUSE_HOURS * 3600

TENANT_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
CONTACT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
PAGE_ID = "1234567890"
SENDER_ID = "psid_42"


# ---------------------------------------------------------------------------
# Pure predicate — the pause gate
# ---------------------------------------------------------------------------


def test_pause_none_is_not_active() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    assert _pause_active(None, now) is False


def test_pause_future_is_active() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    assert _pause_active(now + timedelta(hours=1), now) is True


def test_pause_past_is_not_active() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    assert _pause_active(now - timedelta(seconds=1), now) is False


def test_pause_naive_timestamp_coerced_utc() -> None:
    """A naive future timestamp is treated as UTC, not crashed on."""
    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    naive_future = datetime(2026, 6, 22, 13, 0)  # no tzinfo
    assert _pause_active(naive_future, now) is True


# ---------------------------------------------------------------------------
# Engine handoff — the headline test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paused_contact_blocks_flow_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting bot_paused_until blocks the automation engine from replying.

    With ``is_contact_bot_paused`` True, ``resume_flow_for_dm`` must return True
    (handled → caller also skips the orchestrator) WITHOUT traversing the flow or
    opening a DB session.
    """

    async def _paused(_page_id: str, _sender_id: str) -> bool:
        return True

    traverse_spy = AsyncMock()
    sessionmaker_spy = MagicMock()

    monkeypatch.setattr(flow_engine, "is_contact_bot_paused", _paused)
    monkeypatch.setattr(flow_engine, "_traverse", traverse_spy)
    monkeypatch.setattr(flow_engine, "get_sessionmaker", sessionmaker_spy)

    handled = await flow_engine.resume_flow_for_dm(
        AsyncMock(),
        page_id=PAGE_ID,
        sender_id=SENDER_ID,
        message="hello?",
        token="tok",
    )

    assert handled is True
    traverse_spy.assert_not_called()
    sessionmaker_spy.assert_not_called()  # short-circuit before any DB work


@pytest.mark.asyncio
async def test_unpaused_contact_does_not_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: when not paused and no waiting run exists, the engine proceeds
    to look one up (opens a session) and reports "not handled"."""

    async def _not_paused(_page_id: str, _sender_id: str) -> bool:
        return False

    # Fake session whose run lookup returns None → resume returns False.
    no_run_result = MagicMock()
    no_run_result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=no_run_result)

    class _SM:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session

        async def __aexit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(flow_engine, "is_contact_bot_paused", _not_paused)
    monkeypatch.setattr(flow_engine, "get_sessionmaker", lambda: _SM())

    handled = await flow_engine.resume_flow_for_dm(
        AsyncMock(),
        page_id=PAGE_ID,
        sender_id=SENDER_ID,
        message="hello?",
        token="tok",
    )

    assert handled is False


# ---------------------------------------------------------------------------
# Inbox router — fakes / overrides
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


class _FakeContact:
    def __init__(self) -> None:
        self.id = CONTACT_ID
        self.tenant_id = TENANT_A_ID
        self.page_id = PAGE_ID
        self.sender_id = SENDER_ID
        self.tags: list[Any] = ["vip"]
        self.hot_lead = True
        self.last_interaction_at = datetime.now(timezone.utc)
        self.bot_paused_until = None


class _FakeMapping:
    def __init__(self) -> None:
        self.facebook_page_id = PAGE_ID
        self.tenant_id = TENANT_A_ID
        self.page_access_token_enc = "enc-token"


def _result(scalar: Any = None, scalars_all: list[Any] | None = None) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    scalars = MagicMock()
    scalars.all.return_value = scalars_all or []
    res.scalars.return_value = scalars
    return res


def _make_session(results: list[MagicMock]) -> Any:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=results)
    session.commit = AsyncMock()
    return session


def _install_overrides(
    app: Any, session: Any, tenant: _FakeTenant | None = None
) -> None:
    from rag.auth import current_active_user
    from rag.database.engine import get_async_session
    from rag.routers.deps import require_manager

    resolved_tenant = tenant or _FakeTenant()

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
# Inbox router — DB-less HTTP
# ---------------------------------------------------------------------------


def test_contacts_path_header_mismatch_returns_400(
    client: TestClient, app: Any
) -> None:
    _install_overrides(app, _make_session([_result(scalars_all=[])]))
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_B_ID}/facebook/inbox/contacts",
            headers=_hdr(),
        )
        assert resp.status_code == 400, resp.text
        assert "path tenant_id" in resp.json()["detail"]
    finally:
        _clear_overrides(app)


def test_thread_contact_not_found_returns_404(client: TestClient, app: Any) -> None:
    _install_overrides(app, _make_session([_result(scalar=None)]))
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_A_ID}/facebook/inbox/contacts/{CONTACT_ID}/messages",
            headers=_hdr(),
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "contact_not_found"
    finally:
        _clear_overrides(app)


def test_send_contact_not_found_returns_404(client: TestClient, app: Any) -> None:
    _install_overrides(app, _make_session([_result(scalar=None)]))
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/inbox/contacts/{CONTACT_ID}/send",
            json={"content": "hi"},
            headers=_hdr(),
        )
        assert resp.status_code == 404, resp.text
    finally:
        _clear_overrides(app)


def test_list_contacts_returns_paused_flag(client: TestClient, app: Any) -> None:
    contact = _FakeContact()
    contact.bot_paused_until = datetime.now(timezone.utc) + timedelta(hours=2)
    msg = MagicMock()
    msg.page_id = PAGE_ID
    msg.sender_id = SENDER_ID
    msg.content = "last thing said"
    msg.direction = "inbound"
    msg.created_at = datetime.now(timezone.utc)

    session = _make_session(
        [_result(scalars_all=[contact]), _result(scalars_all=[msg])]
    )
    _install_overrides(app, session)
    try:
        resp = client.get(
            f"/api/tenants/{TENANT_A_ID}/facebook/inbox/contacts",
            headers=_hdr(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 1
        assert body[0]["bot_paused"] is True
        assert body[0]["last_message"]["content"] == "last thing said"
        assert body[0]["hot_lead"] is True
    finally:
        _clear_overrides(app)


def test_manual_send_dispatches_and_pauses_24h(
    client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline inbox test: a human reply sends, logs, and pauses 24h."""
    contact = _FakeContact()
    # send_manual_reply does: load contact, then resolve mapping.
    session = _make_session([_result(scalar=contact), _result(scalar=_FakeMapping())])

    sent: list[dict[str, Any]] = []
    pauses: list[tuple[str, int | None]] = []
    logs: list[dict[str, Any]] = []

    async def _fake_send(_client: Any, *, sender_id: str, text: str, token: str) -> Any:
        sent.append({"sender_id": sender_id, "text": text, "token": token})
        return True, 200, None

    async def _fake_log(**kwargs: Any) -> None:
        logs.append(kwargs)

    async def _fake_pause(sender_id: str, duration_s: int | None = None) -> None:
        pauses.append((sender_id, duration_s))

    monkeypatch.setattr(
        "rag.messenger.routers.inbox.decrypt_token", lambda _enc: "decrypted-tok"
    )
    monkeypatch.setattr("rag.messenger.routers.inbox._send_graph_message", _fake_send)
    monkeypatch.setattr("rag.messenger.routers.inbox.log_contact_message", _fake_log)
    monkeypatch.setattr("rag.messenger.routers.inbox.set_bot_paused", _fake_pause)

    _install_overrides(app, session)
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/inbox/contacts/{CONTACT_ID}/send",
            json={"content": "  Hello from a human  "},
            headers=_hdr(),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sent"] is True
        assert body["bot_paused_until"]  # ISO timestamp present

        # Dispatched the trimmed text with the decrypted token.
        assert len(sent) == 1
        assert sent[0]["text"] == "Hello from a human"
        assert sent[0]["token"] == "decrypted-tok"
        assert sent[0]["sender_id"] == SENDER_ID

        # Logged one outbound transcript row.
        assert len(logs) == 1
        assert logs[0]["direction"] == "outbound"
        assert logs[0]["content"] == "Hello from a human"

        # Paused the bot for 24h via the Redis HITL key...
        assert pauses == [(SENDER_ID, HANDOFF_PAUSE_SECONDS)]
        # ...and stamped the durable DB pause ~24h out.
        assert contact.bot_paused_until is not None
        delta = contact.bot_paused_until - datetime.now(timezone.utc)
        assert timedelta(hours=23, minutes=59) < delta <= timedelta(hours=24)
    finally:
        _clear_overrides(app)


def test_send_graph_failure_returns_502(
    client: TestClient, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    contact = _FakeContact()
    session = _make_session([_result(scalar=contact), _result(scalar=_FakeMapping())])

    async def _fake_send(_client: Any, **_kw: Any) -> Any:
        return False, 400, "graph boom"

    monkeypatch.setattr("rag.messenger.routers.inbox.decrypt_token", lambda _enc: "tok")
    monkeypatch.setattr("rag.messenger.routers.inbox._send_graph_message", _fake_send)

    _install_overrides(app, session)
    try:
        resp = client.post(
            f"/api/tenants/{TENANT_A_ID}/facebook/inbox/contacts/{CONTACT_ID}/send",
            json={"content": "hi"},
            headers=_hdr(),
        )
        assert resp.status_code == 502, resp.text
        assert resp.json()["detail"] == "graph boom"
        # No pause stamped on a failed send.
        assert contact.bot_paused_until is None
    finally:
        _clear_overrides(app)


def test_every_inbox_route_requires_manager(app: Any) -> None:
    """Router lockdown: no inbox route is reachable without require_manager."""
    from rag.routers.deps import require_manager

    inbox_routes = [
        r for r in app.routes if "/facebook/inbox/" in getattr(r, "path", "")
    ]
    assert inbox_routes, "no inbox routes registered"
    for route in inbox_routes:
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert require_manager in dep_calls, f"{route.path} missing require_manager"
