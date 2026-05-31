"""Phase 12 — Meta direct webhook tests.

Covers the GET handshake (verify-token check against the live overlay)
and the POST raw-payload path (HMAC-SHA256 signature verification +
LangGraph dispatch in a background task + outbound send via the Graph
API target).

The background scheduler is overridden so the test can await the
LangGraph + outbound work deterministically — no sleeps, no races.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from rag import messenger_overlay
from rag.main import app
from rag.messenger.routers.webhook import (
    get_graph_runner,
    get_outbound_sender,
    set_event_scheduler,
)
from rag.messenger.schemas import InboundMessage
from rag.messenger.sender import SendResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def overlay_tmp(tmp_path, monkeypatch):
    """Isolate the messenger overlay file per test."""

    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.delenv("MESSENGER_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_APP_SECRET", raising=False)
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)
    return messenger_overlay


@pytest.fixture
def captured_events():
    """Run scheduled events inline (and capture them) instead of fire-and-forget."""

    pending: list[Awaitable[None]] = []

    def _sync_scheduler(coro: Awaitable[None]) -> None:
        pending.append(coro)

    set_event_scheduler(_sync_scheduler)
    try:
        yield pending
    finally:
        set_event_scheduler(None)


class _StubRunner:
    def __init__(self, answer: str = "Plan [1]. Reply YES to book.") -> None:
        self.calls: list[tuple[InboundMessage, str]] = []
        self.answer = answer

    async def __call__(self, payload: InboundMessage, correlation_id: str) -> dict:
        self.calls.append((payload, correlation_id))
        return {
            "answer": self.answer,
            "guardrail_passed": True,
            "citations": (),
            "abstained": False,
            "requires_human_handover": False,
            "llm_prompt_tokens": 5,
            "llm_completion_tokens": 5,
            "llm_total_tokens": 10,
            "llm_model": "groq-llama-3.3-70b",
            "llm_latency_ms": 100,
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


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _envelope(
    text: str = "hello", mid: str = "m_42", sender_id: str = "psid_99"
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page_1",
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": "page_1"},
                        "timestamp": 1731742800,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# GET /messenger/inbound — handshake
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandshake:
    def test_returns_challenge_when_token_matches_overlay(
        self, client: TestClient, overlay_tmp
    ) -> None:
        overlay_tmp.set_verify_token("nexus-verify-token-secret-XX")
        r = client.get(
            "/webhook/messenger/inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "nexus-verify-token-secret-XX",
                "hub.challenge": "12345",
            },
        )
        assert r.status_code == 200
        assert r.text == "12345"

    def test_overlay_overrides_env(
        self, client: TestClient, overlay_tmp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting the env to A and the overlay to B: only B verifies."""

        monkeypatch.setenv("MESSENGER_VERIFY_TOKEN", "ENV-token-value-AAAAAA")
        overlay_tmp.set_verify_token("OVERLAY-token-value-BBBB")

        good = client.get(
            "/webhook/messenger/inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "OVERLAY-token-value-BBBB",
                "hub.challenge": "777",
            },
        )
        bad = client.get(
            "/webhook/messenger/inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "ENV-token-value-AAAAAA",
                "hub.challenge": "777",
            },
        )
        assert good.status_code == 200
        assert good.text == "777"
        assert bad.status_code == 403

    def test_wrong_token_returns_403(self, client: TestClient, overlay_tmp) -> None:
        overlay_tmp.set_verify_token("nexus-verify-token-secret-XX")
        r = client.get(
            "/webhook/messenger/inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "definitely-not-the-right-token",
                "hub.challenge": "1",
            },
        )
        assert r.status_code == 403

    def test_503_when_no_token_configured(
        self, client: TestClient, overlay_tmp
    ) -> None:
        r = client.get(
            "/webhook/messenger/inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "anything",
                "hub.challenge": "1",
            },
        )
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /messenger/inbound — signed raw payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSignedPost:
    def test_dispatches_to_langgraph_and_graph_api(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        stub_sender: _StubSender,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "the-app-secret-value")
        overlay_tmp.set_page_access_token("EAA-page-access-token-9999")

        body = json.dumps(_envelope("Plan a trip to Bali")).encode()
        sig = _sign(body, "the-app-secret-value")

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

        # One event was scheduled. Drain it.
        assert len(captured_events) == 1
        import asyncio

        asyncio.run(captured_events[0])

        # LangGraph received the message text with surface=messenger via _real_graph_runner
        # (we stubbed the runner so we just verify the call here).
        assert len(stub_runner.calls) == 1
        inbound, corr = stub_runner.calls[0]
        assert inbound.user_id == "psid_99"
        assert inbound.message_text == "Plan a trip to Bali"
        assert inbound.channel == "messenger"
        assert corr  # non-empty

        # Outbound was dispatched with target="graph_api".
        stub_sender.dispatch.assert_awaited_once()
        call = stub_sender.dispatch.await_args
        assert call.kwargs["target"] == "graph_api"
        outbound_payload = call.args[0]
        assert outbound_payload.user_id == "psid_99"
        assert outbound_payload.reply.text == stub_runner.answer

    def test_signature_mismatch_returns_403_and_langgraph_not_called(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "the-real-secret")

        body = json.dumps(_envelope()).encode()
        bad_sig = _sign(body, "totally-different-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": bad_sig,
            },
            content=body,
        )
        assert r.status_code == 403
        assert captured_events == []
        assert stub_runner.calls == []

    def test_missing_signature_returns_403(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "the-real-secret")
        body = json.dumps(_envelope()).encode()
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"Content-Type": "application/json"},
            content=body,
        )
        assert r.status_code == 403

    def test_503_when_app_secret_missing(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MESSENGER_APP_SECRET", raising=False)
        body = json.dumps(_envelope()).encode()
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": "sha256=abc"},
            content=body,
        )
        assert r.status_code == 503

    def test_echo_event_is_ignored(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-for-echo-test")
        envelope = _envelope()
        envelope["entry"][0]["messaging"][0]["message"]["is_echo"] = True
        body = json.dumps(envelope).encode()
        sig = _sign(body, "secret-for-echo-test")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        # Nothing scheduled for an echo.
        assert captured_events == []
        assert stub_runner.calls == []

    def test_non_page_object_is_ignored(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-for-other-object")
        body = json.dumps({"object": "instagram", "entry": []}).encode()
        sig = _sign(body, "secret-for-other-object")
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert captured_events == []


# ---------------------------------------------------------------------------
# Phase 15 — multimodal image attachments
# ---------------------------------------------------------------------------


def _envelope_with_attachments(
    *,
    text: str | None = None,
    attachments: list[dict] | None = None,
    mid: str = "m_img",
    sender_id: str = "psid_img",
) -> dict:
    message: dict = {"mid": mid}
    if text is not None:
        message["text"] = text
    if attachments is not None:
        message["attachments"] = attachments
    return {
        "object": "page",
        "entry": [
            {
                "id": "page_1",
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": "page_1"},
                        "timestamp": 1731742800,
                        "message": message,
                    }
                ],
            }
        ],
    }


@pytest.mark.unit
class TestMultimodal:
    def test_image_only_event_dispatches_with_default_caption(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        stub_sender: _StubSender,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "img-secret")
        overlay_tmp.set_page_access_token("EAA-page-access-token-img")

        body = json.dumps(
            _envelope_with_attachments(
                attachments=[
                    {
                        "type": "image",
                        "payload": {"url": "https://scontent.xx.fbcdn.net/x.jpg"},
                    }
                ],
            )
        ).encode()
        sig = _sign(body, "img-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200

        assert len(captured_events) == 1
        import asyncio

        asyncio.run(captured_events[0])

        assert len(stub_runner.calls) == 1
        inbound, _corr = stub_runner.calls[0]
        assert inbound.attachments == [
            {"type": "image", "url": "https://scontent.xx.fbcdn.net/x.jpg"}
        ]
        assert "image" in inbound.message_text.lower()

    def test_text_plus_image_event_threads_both(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "img-secret-2")
        overlay_tmp.set_page_access_token("EAA-tok-1234567890")

        body = json.dumps(
            _envelope_with_attachments(
                text="What is this?",
                attachments=[
                    {
                        "type": "image",
                        "payload": {"url": "https://scontent/y.png"},
                    }
                ],
            )
        ).encode()
        sig = _sign(body, "img-secret-2")

        client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        import asyncio

        asyncio.run(captured_events[0])
        inbound, _ = stub_runner.calls[0]
        assert inbound.message_text == "What is this?"
        assert inbound.attachments == [
            {"type": "image", "url": "https://scontent/y.png"}
        ]

    def test_non_image_attachments_are_dropped(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "img-secret-3")
        overlay_tmp.set_page_access_token("EAA-tok-1234567890")

        body = json.dumps(
            _envelope_with_attachments(
                text="hi",
                attachments=[
                    {"type": "audio", "payload": {"url": "https://a.mp3"}},
                    {"type": "file", "payload": {"url": "https://x.pdf"}},
                ],
            )
        ).encode()
        sig = _sign(body, "img-secret-3")

        client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        import asyncio

        asyncio.run(captured_events[0])
        inbound, _ = stub_runner.calls[0]
        assert inbound.attachments is None

    def test_no_text_no_image_event_skipped(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "img-secret-4")
        body = json.dumps(_envelope_with_attachments()).encode()
        sig = _sign(body, "img-secret-4")
        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert captured_events == []


# ---------------------------------------------------------------------------
# Phase 37 — HITL Handover & Notification Protocol
# ---------------------------------------------------------------------------


def _read_envelope(sender_id: str = "psid_read", page_id: str = "page_1") -> dict:
    """Build a Meta read-receipt envelope (no ``message`` key)."""

    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": 1731742900,
                        "read": {"watermark": 1731742900000},
                    }
                ],
            }
        ],
    }


def _human_echo_envelope(
    *,
    recipient_id: str = "psid_owner_target",
    app_id: str | int | None = 222,
    page_id: str = "page_1",
) -> dict:
    """Build an is_echo envelope as if the human owner replied via Page Inbox."""

    message: dict = {"mid": "m_echo_1", "text": "Hi from the owner", "is_echo": True}
    if app_id is not None:
        message["app_id"] = app_id
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "messaging": [
                    {
                        "sender": {"id": "page_1"},
                        "recipient": {"id": recipient_id},
                        "timestamp": 1731742950,
                        "message": message,
                    }
                ],
            }
        ],
    }


@pytest.mark.unit
class TestHITL:
    def test_read_event_pauses_bot_and_skips_graph(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
        fake_redis,
    ) -> None:
        monkeypatch.setenv("MESSENGER_APP_SECRET", "hitl-read-secret")
        body = json.dumps(_read_envelope(sender_id="psid_read_42")).encode()
        sig = _sign(body, "hitl-read-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        # Graph runner must NOT be called for a read receipt.
        assert stub_runner.calls == []
        # Exactly one background task scheduled: the pause helper.
        assert len(captured_events) == 1

        import asyncio

        asyncio.run(captured_events[0])

        # Pause key now exists in fakeredis.
        async def _check() -> int:
            return await fake_redis.exists("nexus:hitl:paused:psid_read_42")

        assert asyncio.run(_check()) == 1

    def test_human_echo_pauses_bot_for_recipient(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
        fake_redis,
    ) -> None:
        # Our app id = "111", echo carries app_id 222 → human owner via
        # Business Suite. Pause should be set for the *recipient* (the
        # customer the owner is talking to).
        from rag.config import settings as _settings

        monkeypatch.setenv("MESSENGER_APP_SECRET", "hitl-echo-secret")
        monkeypatch.setattr(_settings, "messenger_app_id", "111")

        body = json.dumps(
            _human_echo_envelope(recipient_id="psid_customer_7", app_id=222)
        ).encode()
        sig = _sign(body, "hitl-echo-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert stub_runner.calls == []
        assert len(captured_events) == 1

        import asyncio

        asyncio.run(captured_events[0])

        async def _check() -> int:
            return await fake_redis.exists("nexus:hitl:paused:psid_customer_7")

        assert asyncio.run(_check()) == 1

    def test_bot_own_echo_does_not_pause(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
        fake_redis,
    ) -> None:
        # Echo with app_id matching our own → ignored, no pause scheduled.
        from rag.config import settings as _settings

        monkeypatch.setenv("MESSENGER_APP_SECRET", "hitl-self-echo-secret")
        monkeypatch.setattr(_settings, "messenger_app_id", "111")

        body = json.dumps(
            _human_echo_envelope(recipient_id="psid_customer_8", app_id="111")
        ).encode()
        sig = _sign(body, "hitl-self-echo-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert stub_runner.calls == []
        assert captured_events == []

        import asyncio

        async def _check() -> int:
            return await fake_redis.exists("nexus:hitl:paused:psid_customer_8")

        assert asyncio.run(_check()) == 0

    def test_paused_inbound_is_dropped_and_graph_not_called(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        stub_sender: _StubSender,
        captured_events: list[Awaitable[None]],
        fake_redis,
    ) -> None:
        # Pre-pause the sender, then POST a real inbound message. Expect
        # 200, NO graph call, NO outbound dispatch.
        import asyncio

        from rag.messenger.hitl import set_bot_paused

        asyncio.run(set_bot_paused("psid_99"))

        monkeypatch.setenv("MESSENGER_APP_SECRET", "hitl-pause-secret")

        body = json.dumps(_envelope("Hello, can you help?")).encode()
        sig = _sign(body, "hitl-pause-secret")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert stub_runner.calls == []
        stub_sender.dispatch.assert_not_awaited()
        # No handler scheduled — gatekeeper short-circuited before _scheduler.
        assert captured_events == []
        assert stub_runner.calls == []
