"""Phase 29.2 — Messenger webhook tenant isolation.

Covers:
    * ``resolve_tenant_for_page`` — hit, miss, empty input.
    * Direct Meta webhook drops events whose page_id has no mapping
      (returns 200 with no scheduled task — never 5xx, Meta would retry).
    * Direct Meta webhook attaches the resolved ``tenant_id`` / ``tenant_slug``
      to the InboundMessage handed to the LangGraph runner.
    * ``run_graph(tenant_id=...)`` populates ``NexusState["tenant_id"]``
      so the retrieval nodes' ``_tenant_filter`` never raises.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from rag import messenger_overlay
from rag.main import app
from rag.messenger.routers import webhook as webhook_module
from rag.messenger.routers.webhook import (
    get_graph_runner,
    get_outbound_sender,
    set_event_scheduler,
)
from rag.messenger.schemas import InboundMessage
from rag.messenger.sender import SendResult


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

_TEST_TENANT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_TEST_TENANT_SLUG = "akiro"


class _FakeTenant:
    def __init__(
        self, tid: uuid.UUID = _TEST_TENANT_ID, slug: str = _TEST_TENANT_SLUG
    ) -> None:
        self.id = tid
        self.slug = slug


class _StubRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[InboundMessage, str]] = []

    async def __call__(self, payload: InboundMessage, correlation_id: str) -> dict:
        self.calls.append((payload, correlation_id))
        return {
            "answer": "ok",
            "guardrail_passed": True,
            "citations": (),
            "abstained": False,
            "requires_human_handover": False,
            "llm_prompt_tokens": 1,
            "llm_completion_tokens": 1,
            "llm_total_tokens": 2,
            "llm_model": "stub",
            "llm_latency_ms": 1,
        }


class _StubSender:
    def __init__(self) -> None:
        self.dispatch = AsyncMock(
            return_value=SendResult(
                outcome="delivered",
                status_code=200,
                attempts=1,
                target="graph_api",
            )
        )


# ---------------------------------------------------------------------------
# Resolver — unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveTenantForPage:
    async def test_returns_tenant_when_mapped(self) -> None:
        """When the join matches, the row is returned intact."""
        from rag.messenger.tenant_resolver import resolve_tenant_for_page

        seeded = _FakeTenant()

        class _Result:
            def scalar_one_or_none(self) -> _FakeTenant:
                return seeded

        class _Session:
            async def execute(self, _stmt: object) -> _Result:
                return _Result()

        out = await resolve_tenant_for_page(_Session(), "fb_page_42")  # type: ignore[arg-type]
        assert out is seeded

    async def test_returns_none_when_missing(self) -> None:
        from rag.messenger.tenant_resolver import resolve_tenant_for_page

        class _Result:
            def scalar_one_or_none(self) -> None:
                return None

        class _Session:
            async def execute(self, _stmt: object) -> _Result:
                return _Result()

        out = await resolve_tenant_for_page(_Session(), "fb_page_unmapped")  # type: ignore[arg-type]
        assert out is None

    async def test_returns_none_for_empty_page_id(self) -> None:
        """Defensive: empty string short-circuits without a DB round-trip."""
        from rag.messenger.tenant_resolver import resolve_tenant_for_page

        executed = False

        class _Session:
            async def execute(self, _stmt: object) -> object:  # pragma: no cover
                nonlocal executed
                executed = True
                raise AssertionError("execute() should not be reached")

        out = await resolve_tenant_for_page(_Session(), "")  # type: ignore[arg-type]
        assert out is None
        assert executed is False


# ---------------------------------------------------------------------------
# Webhook — integration with TestClient
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _envelope(
    page_id: str = "page_mapped_1",
    text: str = "hello",
    mid: str = "m_1",
    sender_id: str = "psid_1",
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": 1731742800,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


@pytest.fixture
def overlay_tmp(tmp_path, monkeypatch):
    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.delenv("MESSENGER_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_APP_SECRET", raising=False)
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)
    return messenger_overlay


@pytest.fixture
def captured_events():
    pending: list[Awaitable[None]] = []

    def _sync_scheduler(coro: Awaitable[None]) -> None:
        pending.append(coro)

    set_event_scheduler(_sync_scheduler)
    try:
        yield pending
    finally:
        set_event_scheduler(None)


@pytest.fixture
def stub_runner() -> _StubRunner:
    return _StubRunner()


@pytest.fixture
def stub_sender() -> _StubSender:
    return _StubSender()


@pytest.fixture
def resolver_table(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeTenant]:
    """Per-test routing table. Override the default conftest stub with a
    map the test populates; unmapped page_ids resolve to ``None``."""

    table: dict[str, _FakeTenant] = {}

    async def _resolve(_db: object, page_id: str) -> _FakeTenant | None:
        return table.get(page_id)

    monkeypatch.setattr(webhook_module, "resolve_tenant_for_page", _resolve)
    return table


@pytest.fixture
def client(stub_runner: _StubRunner, stub_sender: _StubSender) -> TestClient:
    async def _runner_override() -> _StubRunner:
        return stub_runner

    async def _sender_override() -> _StubSender:
        return stub_sender

    # ``get_async_session`` is already overridden by the messenger conftest
    # autouse fixture to yield a no-op session, so the resolver call works
    # against the monkeypatched ``resolver_table``.
    app.dependency_overrides[get_graph_runner] = _runner_override
    app.dependency_overrides[get_outbound_sender] = _sender_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_graph_runner, None)
        app.dependency_overrides.pop(get_outbound_sender, None)


@pytest.mark.unit
class TestDirectWebhookTenantBinding:
    def test_unmapped_page_drops_event_with_200(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
        stub_runner: _StubRunner,
        resolver_table: dict[str, _FakeTenant],
    ) -> None:
        """Empty resolver table: Meta still gets 200 (no retry storm), but
        nothing reaches the graph."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "phase29-test-secret")
        body = json.dumps(_envelope(page_id="page_orphan")).encode()
        sig = _sign(body, "phase29-test-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
            content=body,
        )
        assert r.status_code == 200
        assert r.text == "EVENT_RECEIVED"
        assert captured_events == []
        assert stub_runner.calls == []

    def test_mapped_page_passes_tenant_into_graph(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
        stub_runner: _StubRunner,
        resolver_table: dict[str, _FakeTenant],
    ) -> None:
        """Seed page_id → tenant; verify the inbound carries both id + slug
        when the background task runs."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "phase29-test-secret")
        overlay_tmp.set_page_access_token("EAA-test-page-access-token-9999")

        resolver_table["page_akiro"] = _FakeTenant()
        body = json.dumps(_envelope(page_id="page_akiro")).encode()
        sig = _sign(body, "phase29-test-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
            content=body,
        )
        assert r.status_code == 200

        # Drain the scheduled background task so we can inspect the runner call.
        assert len(captured_events) == 1
        import asyncio

        asyncio.run(captured_events[0])

        assert len(stub_runner.calls) == 1
        inbound, _ = stub_runner.calls[0]
        assert inbound.tenant_id == _TEST_TENANT_ID
        assert inbound.tenant_slug == _TEST_TENANT_SLUG
        assert inbound.page_id == "page_akiro"


# ---------------------------------------------------------------------------
# run_graph propagates tenant_id into NexusState
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunGraphPropagatesTenant:
    async def test_state_carries_tenant_slug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``run_graph(tenant_id="hunter")`` must surface as
        ``state['tenant_id'] = 'hunter'`` before the graph runs."""
        from rag.orchestrator import graph as graph_module

        captured: dict[str, object] = {}

        class _StubGraph:
            async def ainvoke(self, state: dict, config: dict) -> dict:  # type: ignore[type-arg]
                captured["state"] = dict(state)
                return {"answer": "ok"}

        monkeypatch.setattr(graph_module, "get_graph", lambda: _StubGraph())

        result = await graph_module.run_graph(
            query="q",
            thread_key="thread-1",
            correlation_id="corr-1",
            surface="messenger",
            tenant_id="hunter",
        )
        assert result == {"answer": "ok"}
        assert captured["state"]["tenant_id"] == "hunter"  # type: ignore[index]

    async def test_omitted_tenant_leaves_state_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a caller forgets to pass tenant_id, the orchestrator's
        ``_tenant_filter`` is the canonical place that raises — run_graph
        itself just leaves the field unset."""
        from rag.orchestrator import graph as graph_module

        captured: dict[str, object] = {}

        class _StubGraph:
            async def ainvoke(self, state: dict, config: dict) -> dict:  # type: ignore[type-arg]
                captured["state"] = dict(state)
                return {"answer": "ok"}

        monkeypatch.setattr(graph_module, "get_graph", lambda: _StubGraph())

        await graph_module.run_graph(
            query="q",
            thread_key="thread-2",
            correlation_id="corr-2",
            surface="messenger",
        )
        assert "tenant_id" not in captured["state"]  # type: ignore[operator]
