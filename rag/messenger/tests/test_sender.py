"""Phase 6 OutboundSender tests — covers happy path, transport failure,
4xx → DLQ, 5xx → retry queue, skipped when no URL configured."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from rag.config import settings
from rag.messenger.payloads import (
    OutboundMetadata,
    OutboundPayload,
    ReplyBlock,
    TokenUsage,
)
from rag.messenger.queue import RedisOutboundQueue
from rag.messenger.sender import OutboundSender, SendResult


def _payload() -> OutboundPayload:
    return OutboundPayload(
        correlation_id="corr_test",
        user_id="psid_99",
        channel="messenger",
        reply=ReplyBlock(text="Plan [1]. Reply YES to book."),
        metadata=OutboundMetadata(tokens=TokenUsage(prompt=10, completion=5, total=15)),
    )


class _MockQueue:
    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.dead_letter = AsyncMock()


class _ResponseStub:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _ClientStub:
    """Mimics an httpx.AsyncClient used as an async context manager."""

    def __init__(self, response: _ResponseStub | None = None, raise_exc: Exception | None = None) -> None:
        self._response = response
        self._raise_exc = raise_exc
        self.last_url: str | None = None
        self.last_body: dict[str, Any] | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url: str, *, json: dict) -> _ResponseStub:
        self.last_url = url
        self.last_body = json
        if self._raise_exc:
            raise self._raise_exc
        assert self._response is not None
        return self._response


def _factory(client: _ClientStub):
    return lambda: client


# ---------------------------------------------------------------------------
# Skipped path (no URL)
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_skipped_when_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = _MockQueue()
    sender = OutboundSender(queue=queue, client_factory=_factory(_ClientStub(_ResponseStub(200))))  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "make_webhook_url", None, raising=False)
    result = await sender.dispatch(_payload(), target_url=None)
    assert result.outcome == "skipped"
    queue.enqueue.assert_not_awaited()
    queue.dead_letter.assert_not_awaited()


@pytest.mark.unit
async def test_uses_settings_url_when_target_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "make_webhook_url", "https://make.com/hook", raising=False
    )
    client = _ClientStub(_ResponseStub(200))
    queue = _MockQueue()
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target_url=None)
    assert result.outcome == "delivered"
    assert client.last_url == "https://make.com/hook"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_delivered_on_2xx() -> None:
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(200))
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target_url="https://hook.x")
    assert result.outcome == "delivered"
    assert result.status_code == 200
    assert result.attempts == 1
    queue.enqueue.assert_not_awaited()
    queue.dead_letter.assert_not_awaited()
    # Posted body shape sanity-check
    assert client.last_body and client.last_body["correlation_id"] == "corr_test"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_transport_error_enqueues_for_retry() -> None:
    queue = _MockQueue()
    client = _ClientStub(raise_exc=httpx.ConnectError("refused"))
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target_url="https://hook.x")
    assert result.outcome == "queued"
    assert result.attempts == 1
    queue.enqueue.assert_awaited_once()
    queue.dead_letter.assert_not_awaited()


@pytest.mark.unit
async def test_5xx_enqueues_for_retry() -> None:
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(502, "bad gateway"))
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target_url="https://hook.x")
    assert result.outcome == "queued"
    assert result.status_code == 502
    queue.enqueue.assert_awaited_once()
    queue.dead_letter.assert_not_awaited()


@pytest.mark.unit
async def test_4xx_goes_straight_to_dlq() -> None:
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(404, "not found"))
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target_url="https://hook.x")
    assert result.outcome == "dead_letter"
    assert result.status_code == 404
    queue.dead_letter.assert_awaited_once()
    queue.enqueue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 12 — Graph API target
# ---------------------------------------------------------------------------


class _JsonResponseStub:
    """Like ``_ResponseStub`` but also exposes ``.json()`` for Graph API
    error bodies."""

    def __init__(self, status_code: int, body: dict | str = "") -> None:
        self.status_code = status_code
        if isinstance(body, dict):
            self._json = body
            self.text = ""
        else:
            self._json = None
            self.text = body

    def json(self) -> dict:
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.mark.unit
async def test_graph_api_send_uses_current_page_access_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The Graph API target reads the page access token from the overlay
    on every call — proves UI rotations take effect without restart."""

    from rag import messenger_overlay

    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)
    messenger_overlay.set_page_access_token("first-token-abc-12345")

    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(200))
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]

    result = await sender.dispatch(_payload(), target="graph_api")
    assert result.outcome == "delivered"
    assert client.last_url is not None
    assert "access_token=first-token-abc-12345" in client.last_url
    assert client.last_url.startswith(
        "https://graph.facebook.com/v21.0/me/messages"
    )
    assert client.last_body == {
        "recipient": {"id": "psid_99"},
        "messaging_type": "RESPONSE",
        "message": {"text": "Plan . Reply YES to book."},
    }

    # Rotate the token. The next send must use the NEW value.
    messenger_overlay.set_page_access_token("second-token-xyz-99999")
    client2 = _ClientStub(_ResponseStub(200))
    sender2 = OutboundSender(queue=queue, client_factory=_factory(client2))  # type: ignore[arg-type]
    await sender2.dispatch(_payload(), target="graph_api")
    assert client2.last_url is not None
    assert "access_token=second-token-xyz-99999" in client2.last_url


@pytest.mark.unit
async def test_graph_api_token_missing_goes_to_dlq(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from rag import messenger_overlay

    monkeypatch.setattr(
        messenger_overlay, "_OVERLAY_PATH", tmp_path / ".messenger_override.json"
    )
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)

    queue = _MockQueue()
    sender = OutboundSender(
        queue=queue, client_factory=_factory(_ClientStub(_ResponseStub(200)))  # type: ignore[arg-type]
    )
    result = await sender.dispatch(_payload(), target="graph_api")
    assert result.outcome == "dead_letter"
    assert result.error and "missing" in result.error.lower()


@pytest.mark.unit
async def test_graph_api_token_expired_code_190_dlq(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """FB error code 190 = OAuthException (token expired/invalid). Not
    retryable — sending the same token again will keep failing."""

    from rag import messenger_overlay

    monkeypatch.setattr(
        messenger_overlay, "_OVERLAY_PATH", tmp_path / ".messenger_override.json"
    )
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    messenger_overlay.set_page_access_token("expired-token-1234567890")

    queue = _MockQueue()
    client = _ClientStub(
        _JsonResponseStub(  # type: ignore[arg-type]
            401,
            body={
                "error": {
                    "code": 190,
                    "error_subcode": 463,
                    "message": "Error validating access token: Session has expired.",
                    "type": "OAuthException",
                }
            },
        )
    )
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target="graph_api")
    assert result.outcome == "dead_letter"
    assert result.status_code == 401
    queue.dead_letter.assert_awaited_once()
    queue.enqueue.assert_not_awaited()


@pytest.mark.unit
async def test_graph_api_rate_limit_subcode_613_enqueues_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """FB error subcode 613 = rate limit. Retryable."""

    from rag import messenger_overlay

    monkeypatch.setattr(
        messenger_overlay, "_OVERLAY_PATH", tmp_path / ".messenger_override.json"
    )
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    messenger_overlay.set_page_access_token("valid-token-but-throttled1")

    queue = _MockQueue()
    client = _ClientStub(
        _JsonResponseStub(  # type: ignore[arg-type]
            400,
            body={
                "error": {
                    "code": 100,
                    "error_subcode": 613,
                    "message": "Calls to this api have exceeded the rate limit.",
                }
            },
        )
    )
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target="graph_api")
    assert result.outcome == "queued"
    queue.enqueue.assert_awaited_once()
    queue.dead_letter.assert_not_awaited()
    enqueued = queue.enqueue.await_args.args[0]
    assert enqueued.target == "graph_api"


@pytest.mark.unit
async def test_graph_api_5xx_enqueues_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from rag import messenger_overlay

    monkeypatch.setattr(
        messenger_overlay, "_OVERLAY_PATH", tmp_path / ".messenger_override.json"
    )
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    messenger_overlay.set_page_access_token("page-token-graph-5xx-9999")

    queue = _MockQueue()
    client = _ClientStub(_JsonResponseStub(503, body={"error": {"code": 1}}))  # type: ignore[arg-type]
    sender = OutboundSender(queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    result = await sender.dispatch(_payload(), target="graph_api")
    assert result.outcome == "queued"
    queue.enqueue.assert_awaited_once()
