"""Phase 3 webhook tests — schema validation, auth, graph dispatch via
dependency override (no real LangGraph invocation here)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag.messenger.main import app
from rag.messenger.routers.webhook import get_graph_runner
from rag.messenger.schemas import InboundMessage


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
# Graph runner override
# ---------------------------------------------------------------------------

class _StubRunner:
    """Records calls and returns a canned graph result."""

    def __init__(self, response: dict | None = None, raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple[InboundMessage, str]] = []
        self.response = response or {
            "answer": "Welcome to our service — pricing starts at $99 [1].",
            "guardrail_passed": True,
            "citations": ("note-1",),
            "abstained": False,
        }
        self.raise_exc = raise_exc

    async def __call__(self, payload: InboundMessage, correlation_id: str) -> dict:
        self.calls.append((payload, correlation_id))
        if self.raise_exc:
            raise self.raise_exc
        return self.response


@pytest.fixture
def stub_runner() -> _StubRunner:
    return _StubRunner()


@pytest.fixture
def client(stub_runner: _StubRunner) -> TestClient:
    async def _override() -> _StubRunner:
        return stub_runner

    app.dependency_overrides[get_graph_runner] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_graph_runner, None)


# ---------------------------------------------------------------------------
# Health (unchanged, no graph involvement)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "nexus-messenger"
        assert body["version"]

    def test_api_health_compat(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Inbound — happy path + dispatch
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInbound:
    def test_dispatches_to_runner(
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
        assert body["received_at"] > 0

        assert len(stub_runner.calls) == 1
        called_payload, called_cid = stub_runner.calls[0]
        assert called_payload.user_id == "psid_12345"
        assert called_payload.message_text.startswith("Hello")
        assert called_cid.startswith("corr_")

    def test_preserves_provided_correlation_id(
        self, client: TestClient, stub_runner: _StubRunner
    ) -> None:
        cid = "n8n_run_abc123"
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(correlation_id=cid),
        )
        assert r.status_code == 200
        assert r.json()["correlation_id"] == cid
        assert stub_runner.calls[0][1] == cid

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
        assert body["status"] == "accepted"
        assert "human" in body["reply_text"].lower() or "route" in body["reply_text"].lower()

    def test_empty_runner_answer_falls_back_to_abstention(
        self, client: TestClient
    ) -> None:
        empty = _StubRunner(response={"answer": "   "})

        async def _override() -> _StubRunner:
            return empty

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
        assert body["reply_text"]
        assert "human" in body["reply_text"].lower() or "route" in body["reply_text"].lower()


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

    def test_rejects_unknown_channel(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(channel="signal"),
        )
        assert r.status_code == 422

    def test_rejects_oversize_message(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(message_text="x" * 2001),
        )
        assert r.status_code == 422

    def test_rejects_extra_fields(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(unexpected="injection"),
        )
        assert r.status_code == 422

    def test_rejects_negative_timestamp(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Webhook-Api-Key": "test-key"},
            json=_payload(timestamp=-1),
        )
        assert r.status_code == 422


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
# Opt-out (no graph involvement)
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
        assert body["correlation_id"]
        assert body["received_at"] > 0

    def test_optout_rejects_missing_user_id(self, client: TestClient) -> None:
        r = client.post(
            "/webhook/messenger/optout",
            headers={"X-Webhook-Api-Key": "test-key"},
            json={"channel": "messenger"},
        )
        assert r.status_code == 422
