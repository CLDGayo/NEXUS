"""Phase 6 webhook tests — schema validation, auth, graph dispatch, AND
outbound sender wiring (covers skipped, delivered, queued outcomes)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from rag.messenger.main import app
from rag.messenger.routers.webhook import (
    get_graph_runner,
    get_outbound_sender,
)
from rag.messenger.schemas import InboundMessage
from rag.messenger.sender import SendResult


def _payload(**overrides) -> dict:
    base: dict = {
        "user_id": "psid_12345",
        "message_text": "Hello, I have a question about pricing.",
        "timestamp": 1731742800,
        "channel": "messenger",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubRunner:
    def __init__(self, response: dict | None = None, raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple[InboundMessage, str]] = []
        self.response = response or {
            "answer": "Plan [1]. Reply YES to book.",
            "guardrail_passed": True,
            "citations": ("note-1",),
            "abstained": False,
            "requires_human_handover": False,
            "llm_prompt_tokens": 100,
            "llm_completion_tokens": 20,
            "llm_total_tokens": 120,
            "llm_model": "groq-llama-3.3-70b",
            "llm_latency_ms": 800,
        }
        self.raise_exc = raise_exc

    async def __call__(self, payload: InboundMessage, correlation_id: str) -> dict:
        self.calls.append((payload, correlation_id))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


class _StubSender:
    def __init__(self, send_result: SendResult | None = None) -> None:
        self.calls: list[tuple] = []
        self.dispatch = AsyncMock(
            return_value=send_result
            or SendResult(outcome="delivered", status_code=200, attempts=1)
        )


@pytest.fixture
def stub_runner() -> _StubRunner:
    return _StubRunner()


@pytest.fixture
def stub_sender() -> _StubSender:
    return _StubSender()


@pytest.fixture
def client(stub_runner: _StubRunner, stub_sender: _StubSender) -> TestClient:
    async def _runner_override() -> _StubRunner:
        return stub_runner

    async def _sender_override() -> _StubSender:
        return stub_sender

    app.dependency_overrides[get_graph_runner] = _runner_override
    app.dependency_overrides[get_outbound_sender] = _sender_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_graph_runner, None)
        app.dependency_overrides.pop(get_outbound_sender, None)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "nexus-messenger"


# ---------------------------------------------------------------------------
# Inbound — sync ack path
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInboundSyncAck:
    def test_dispatches_to_runner_and_returns_reply(
        self, client: TestClient, stub_runner: _StubRunner
    ) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "accepted"
        assert body["reply_text"] == stub_runner.response["answer"]
        assert body["latency_ms"] >= 0
        assert body["correlation_id"].startswith("corr_")

    def test_runner_exception_falls_back_to_abstention(
        self, client: TestClient
    ) -> None:
        boom = _StubRunner(raise_exc=RuntimeError("graph blew up"))

        async def _override() -> _StubRunner:
            return boom

        app.dependency_overrides[get_graph_runner] = _override
        try:
            r = client.post(
                "/webhook/messenger/inbound",
                headers={"X-Webhook-Api-Key": "test-key"},
                json=_payload(),
            )
        finally:
            app.dependency_overrides.pop(get_graph_runner, None)

        assert r.status_code == 200
        body = r.json()
        assert "human" in body["reply_text"].lower() or "route" in body["reply_text"].lower()


# ---------------------------------------------------------------------------
# Outbound dispatch wiring
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOutboundDispatch:
    def test_skipped_when_no_url_or_flag(
        self, client: TestClient, stub_sender: _StubSender, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rag.config import settings as cfg

        monkeypatch.setattr(cfg, "outbound_dispatch_enabled", False, raising=False)
        monkeypatch.setattr(cfg, "make_webhook_url", None, raising=False)

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(),
        )
        assert r.status_code == 200
        stub_sender.dispatch.assert_not_called()

    def test_dispatches_when_per_request_url_supplied(
        self, client: TestClient, stub_sender: _StubSender
    ) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(outbound_url="https://make.com/hook/abc"),
        )
        assert r.status_code == 200
        stub_sender.dispatch.assert_awaited_once()
        call = stub_sender.dispatch.await_args
        # First positional: the OutboundPayload
        outbound = call.args[0]
        assert outbound.user_id == "psid_12345"
        assert outbound.reply.text  # populated
        assert call.kwargs["target_url"] == "https://make.com/hook/abc"

    def test_dispatches_when_env_flag_enabled(
        self, client: TestClient, stub_sender: _StubSender, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rag.config import settings as cfg

        monkeypatch.setattr(cfg, "outbound_dispatch_enabled", True, raising=False)
        monkeypatch.setattr(
            cfg, "make_webhook_url", "https://make.com/global", raising=False
        )

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(),
        )
        assert r.status_code == 200
        stub_sender.dispatch.assert_awaited_once()
        assert stub_sender.dispatch.await_args.kwargs["target_url"] == "https://make.com/global"

    def test_sender_failure_does_not_break_ack(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boom_sender = _StubSender()
        boom_sender.dispatch = AsyncMock(side_effect=RuntimeError("redis down"))

        async def _override() -> _StubSender:
            return boom_sender

        app.dependency_overrides[get_outbound_sender] = _override
        try:
            r = client.post(
                "/webhook/messenger/inbound",
                headers={"X-Webhook-Api-Key": "test-key"},
                json=_payload(outbound_url="https://make.com/hook"),
            )
        finally:
            app.dependency_overrides.pop(get_outbound_sender, None)

        assert r.status_code == 200
        assert r.json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestValidation:
    def test_rejects_empty_text(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(message_text=""),
        )
        assert r.status_code == 422

    def test_rejects_extra_fields(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(unexpected="injection"),
        )
        assert r.status_code == 422

    def test_accepts_outbound_url_field(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(outbound_url="https://hook.x/abc"),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAuth:
    def test_rejects_missing_api_key(self, client: TestClient) -> None:
        r = client.post("/webhook/messenger/inbound", json=_payload())
        assert r.status_code == 401

    def test_rejects_wrong_api_key(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "wrong"},
            json=_payload(),
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOptOut:
    def test_accepts_optout(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/optout",
            headers={"X-Webhook-Api-Key": "test-key"},
            json={"user_id": "psid_12345", "channel": "messenger"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
