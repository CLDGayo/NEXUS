"""Phase 21 — webhook coalescing, content-keyed idempotency, thread lock.

The Meta direct path is responsible for collapsing a single user turn
that arrives as multiple ``messaging[]`` events into exactly one
background task. It also has to dedupe retries that present with a fresh
``mid`` (the previous body-hash key couldn't), and serialize concurrent
turns for the same user behind a per-thread lock.
"""

from __future__ import annotations

import asyncio
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
# Local fixtures (parallel to test_webhook_direct.py)
# ---------------------------------------------------------------------------

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


class _StubRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[InboundMessage, str]] = []

    async def __call__(self, payload: InboundMessage, correlation_id: str) -> dict:
        self.calls.append((payload, correlation_id))
        return {"answer": "ok", "guardrail_passed": True}


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


def _event(
    *,
    sender_id: str = "psid_99",
    mid: str,
    text: str | None = None,
    attachments: list[dict] | None = None,
    ts_ms: int = 1_731_742_800_000,
) -> dict:
    message: dict = {"mid": mid}
    if text is not None:
        message["text"] = text
    if attachments is not None:
        message["attachments"] = attachments
    return {
        "sender": {"id": sender_id},
        "recipient": {"id": "page_1"},
        "timestamp": ts_ms,
        "message": message,
    }


def _envelope(events: list[dict]) -> dict:
    return {
        "object": "page",
        "entry": [{"id": "page_1", "messaging": events}],
    }


def _post(client: TestClient, envelope: dict, secret: str) -> int:
    body = json.dumps(envelope).encode()
    sig = _sign(body, secret)
    return client.post(
        "/webhook/messenger/inbound",
        headers={"X-Hub-Signature-256": sig},
        content=body,
    ).status_code


# ---------------------------------------------------------------------------
# Coalescing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCoalescing:
    def test_text_and_image_in_one_envelope_coalesce_to_one_task(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        stub_runner: _StubRunner,
        captured_events: list[Awaitable[None]],
    ) -> None:
        """Meta sometimes splits one user turn into two messaging events
        (one carrying the text, one carrying the image attachment).
        Phase 21 merges them into a single InboundMessage."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-coalesce-1")
        overlay_tmp.set_page_access_token("EAA-token-coalesce-XX")

        envelope = _envelope(
            [
                _event(mid="m_text", text="what is this?", ts_ms=1_731_742_800_000),
                _event(
                    mid="m_img",
                    attachments=[
                        {
                            "type": "image",
                            "payload": {"url": "https://scontent/x.jpg"},
                        }
                    ],
                    ts_ms=1_731_742_800_500,  # 0.5s later — same second bucket
                ),
            ]
        )
        assert _post(client, envelope, "secret-coalesce-1") == 200

        assert len(captured_events) == 1
        asyncio.run(captured_events[0])
        assert len(stub_runner.calls) == 1
        inbound, _ = stub_runner.calls[0]
        assert inbound.message_text == "what is this?"
        assert inbound.attachments == [
            {"type": "image", "url": "https://scontent/x.jpg"}
        ]

    def test_two_envelopes_with_different_mids_same_content_dedup(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        """Meta retry: same user sends same text, but Meta's mid changes.
        Old body-hash key broke; content-keyed claim must catch it."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-dedup-1")
        overlay_tmp.set_page_access_token("EAA-token-dedup-XYZ123")

        env1 = _envelope([_event(mid="m_original", text="hello world")])
        env2 = _envelope([_event(mid="m_retry_fresh_mid", text="hello world")])

        assert _post(client, env1, "secret-dedup-1") == 200
        assert _post(client, env2, "secret-dedup-1") == 200
        assert len(captured_events) == 1
        asyncio.run(captured_events[0])

    def test_distinct_messages_from_same_user_both_scheduled(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        """Real follow-up text from the same user must NOT dedupe."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-distinct-1")
        overlay_tmp.set_page_access_token("EAA-token-distinct-XYZ12")

        env1 = _envelope([_event(mid="m_1", text="first question")])
        env2 = _envelope([_event(mid="m_2", text="second question")])

        assert _post(client, env1, "secret-distinct-1") == 200
        # Drain + release thread lock so the second turn can acquire it.
        asyncio.run(captured_events[0])

        assert _post(client, env2, "secret-distinct-1") == 200
        assert len(captured_events) == 2
        asyncio.run(captured_events[1])


# ---------------------------------------------------------------------------
# Thread lock
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThreadLock:
    def test_back_to_back_envelopes_drop_second_until_first_releases(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        """While the first task is still in-flight (we haven't drained
        it yet), a second envelope from the SAME user with DIFFERENT
        content must be dropped by the per-thread lock — not by content
        idempotency, since the text differs."""

        monkeypatch.setenv("MESSENGER_APP_SECRET", "secret-lock-1")
        overlay_tmp.set_page_access_token("EAA-token-lock-XYZ12345")

        env1 = _envelope([_event(mid="m_a", text="alpha message")])
        env2 = _envelope([_event(mid="m_b", text="beta message")])

        assert _post(client, env1, "secret-lock-1") == 200
        # Do NOT drain captured_events[0] yet — lock is still held.
        assert _post(client, env2, "secret-lock-1") == 200
        assert len(captured_events) == 1  # second got lock-dropped
        # Drain the survivor so the captured coroutine doesn't leak.
        asyncio.run(captured_events[0])
