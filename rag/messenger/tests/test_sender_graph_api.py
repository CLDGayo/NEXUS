"""Phase 32.6 — multi-body Graph API dispatch.

Pins the new behaviour: when a carousel + text reply is shipped as two
Send API bodies, a non-retryable failure on one body must NOT silently
swallow the other. The text-continuity bubble has to survive a Meta
template validation 400 on the carousel, and a transport / 5xx error on
one body must enqueue only that body for retry.

Also asserts the structured ``image_urls`` / ``image_fingerprint`` log
fields are emitted so future ``(#100) ... should represent a valid URL``
incidents are debuggable from logs.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from rag.messenger.payloads import (
    GenericTemplateElement,
    OutboundMetadata,
    OutboundPayload,
    ProductCarouselBlock,
    ReplyBlock,
)
from rag.messenger.sender import OutboundSender


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _payload_with_carousel_and_text() -> OutboundPayload:
    """A payload that produces TWO Send API bodies: carousel + text."""

    return OutboundPayload(
        correlation_id="corr_p326",
        user_id="psid_42",
        channel="messenger",
        reply=ReplyBlock(
            text="Here are 3 options I found.",
            carousel=ProductCarouselBlock(
                elements=[
                    GenericTemplateElement(
                        title="Widget Mk II",
                        subtitle="$19.99 · 12 in stock",
                        image_url="https://chat.nexus.gayo-sphere.cloud/api/objects/abc",  # type: ignore[arg-type]
                    ),
                ],
            ),
        ),
        metadata=OutboundMetadata(),
    )


def _payload_text_only() -> OutboundPayload:
    return OutboundPayload(
        correlation_id="corr_text_only",
        user_id="psid_42",
        channel="messenger",
        reply=ReplyBlock(text="No carousel — just words."),
        metadata=OutboundMetadata(),
    )


class _MockQueue:
    def __init__(self) -> None:
        self.enqueue = AsyncMock()
        self.dead_letter = AsyncMock()


class _SequencedResponse:
    """One response in a queue of stubs. JSON body optional."""

    def __init__(self, status_code: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)[:200]

    def json(self) -> dict[str, Any]:
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _SequencedClient:
    """Mimics httpx.AsyncClient but pops a different response for each
    POST. Used to assert per-body outcomes when ``_dispatch_graph_api``
    walks the carousel/text bodies."""

    def __init__(self, responses: list[_SequencedResponse]) -> None:
        self._responses = list(responses)
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_SequencedClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any]) -> _SequencedResponse:
        self.posts.append({"url": url, "body": json})
        if not self._responses:
            raise AssertionError("Unexpected extra POST — response queue exhausted")
        return self._responses.pop(0)


def _factory_for(client: _SequencedClient):
    """Same client instance every call — its response queue is what
    sequences per-body outcomes."""

    return lambda: client


@pytest.fixture(autouse=True)
def _seed_page_access_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from rag import messenger_overlay

    monkeypatch.setattr(
        messenger_overlay, "_OVERLAY_PATH", tmp_path / ".messenger_override.json"
    )
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    messenger_overlay.set_page_access_token("test-token-phase-326-xxxxxxxx")


# ---------------------------------------------------------------------------
# Decoupling: text survives a carousel 400
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_text_bubble_survives_carousel_400() -> None:
    """Carousel non-retryable 400 must not silently drop the text body.

    Before Phase 32.6, ``_dispatch_graph_api`` returned on the first
    failed POST. The carousel 400'd, the text body was never sent, and
    the user got no reply at all — Architect-reported "text drop"
    symptom.
    """

    queue = _MockQueue()
    client = _SequencedClient(
        [
            _SequencedResponse(
                400,
                body={
                    "error": {
                        "code": 100,
                        "error_subcode": 0,
                        "message": (
                            "(#100) name_placeholder[elements][0][image_url] "
                            "should represent a valid URL"
                        ),
                    }
                },
            ),
            _SequencedResponse(200),
        ]
    )
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    result = await sender.dispatch(
        _payload_with_carousel_and_text(), target="graph_api"
    )

    assert result.outcome == "delivered", (
        "text body must ship even though the carousel POST failed 400"
    )
    assert len(client.posts) == 2
    assert "attachment" in client.posts[0]["body"]["message"]
    assert client.posts[1]["body"]["message"] == {"text": "Here are 3 options I found."}
    queue.dead_letter.assert_not_awaited()
    queue.enqueue.assert_not_awaited()


@pytest.mark.unit
async def test_carousel_survives_text_400() -> None:
    """Mirror case: a text-body 400 must not stop the carousel from
    shipping. (Today's order is carousel-first, so this exercises the
    second-body-only failure path.)"""

    queue = _MockQueue()
    client = _SequencedClient(
        [
            _SequencedResponse(200),
            _SequencedResponse(
                400,
                body={
                    "error": {
                        "code": 100,
                        "message": "(#100) Invalid parameter",
                    }
                },
            ),
        ]
    )
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    result = await sender.dispatch(
        _payload_with_carousel_and_text(), target="graph_api"
    )

    assert result.outcome == "delivered"
    assert len(client.posts) == 2
    queue.dead_letter.assert_not_awaited()
    queue.enqueue.assert_not_awaited()


@pytest.mark.unit
async def test_all_bodies_400_dead_letters() -> None:
    """If every body 400s non-retryably, the dispatch ends in DLQ."""

    queue = _MockQueue()
    err_body = {"error": {"code": 100, "message": "(#100) bad"}}
    client = _SequencedClient(
        [_SequencedResponse(400, body=err_body), _SequencedResponse(400, body=err_body)]
    )
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    result = await sender.dispatch(
        _payload_with_carousel_and_text(), target="graph_api"
    )

    assert result.outcome == "dead_letter"
    assert len(client.posts) == 2
    queue.dead_letter.assert_awaited_once()
    queue.enqueue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Retry isolation: only the failing body gets enqueued
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_text_5xx_enqueues_text_only_after_carousel_delivers() -> None:
    """When the carousel ships successfully and the text body hits a
    5xx, only the text body should be in the retry queue — not the
    whole payload (which would re-send the carousel on the worker)."""

    queue = _MockQueue()
    client = _SequencedClient(
        [
            _SequencedResponse(200),
            _SequencedResponse(503, body={"error": {"code": 1}}),
        ]
    )
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    result = await sender.dispatch(
        _payload_with_carousel_and_text(), target="graph_api"
    )

    # Carousel landed; result reflects the delivered count.
    assert result.outcome == "delivered"
    queue.dead_letter.assert_not_awaited()
    queue.enqueue.assert_awaited_once()

    enqueued = queue.enqueue.await_args.args[0]
    assert enqueued.target == "graph_api"
    # The retried payload must be text-only — the carousel was scrubbed
    # so the worker doesn't double-ship the cards.
    retried_reply = enqueued.payload["reply"]
    assert retried_reply.get("carousel") is None
    assert retried_reply.get("text") == "Here are 3 options I found."


@pytest.mark.unit
async def test_carousel_transport_error_enqueues_carousel_only() -> None:
    """A transport-level failure on the carousel POST must enqueue only
    the carousel for retry and stop the dispatch (don't keep firing
    bodies through a broken transport)."""

    queue = _MockQueue()

    class _FlakyClient(_SequencedClient):
        async def post(self, url: str, *, json: dict[str, Any]) -> _SequencedResponse:
            self.posts.append({"url": url, "body": json})
            raise httpx.ConnectError("refused")

    client = _FlakyClient([])
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    result = await sender.dispatch(
        _payload_with_carousel_and_text(), target="graph_api"
    )

    assert result.outcome == "queued"
    # Dispatch stopped after the failed body — no second POST attempted.
    assert len(client.posts) == 1
    queue.enqueue.assert_awaited_once()
    queue.dead_letter.assert_not_awaited()

    enqueued = queue.enqueue.await_args.args[0]
    retried_reply = enqueued.payload["reply"]
    # Carousel preserved; text scrubbed so the worker only ships the
    # body that actually failed.
    assert retried_reply.get("carousel") is not None
    assert retried_reply.get("text") is None


# ---------------------------------------------------------------------------
# Diagnostic logging: image URL fingerprint
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_dispatch_log_includes_image_fingerprint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = _MockQueue()
    client = _SequencedClient(
        [_SequencedResponse(200), _SequencedResponse(200)]
    )
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger="rag.messenger.sender"):
        await sender.dispatch(
            _payload_with_carousel_and_text(), target="graph_api"
        )

    records = [r for r in caplog.records if "outbound.graph_api" in r.getMessage()]
    dispatch_lines = [r.getMessage() for r in records if "dispatch" in r.getMessage()]
    delivered_lines = [r.getMessage() for r in records if "delivered" in r.getMessage()]

    assert dispatch_lines, "expected outbound.graph_api dispatch log line"
    assert delivered_lines, "expected outbound.graph_api delivered log line"
    assert "image_urls=1" in dispatch_lines[0]
    assert "image_fingerprint=" in dispatch_lines[0]
    assert "image_fingerprint=-" not in dispatch_lines[0]


@pytest.mark.unit
async def test_dispatch_log_text_only_fingerprint_is_dash(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = _MockQueue()
    client = _SequencedClient([_SequencedResponse(200)])
    sender = OutboundSender(queue=queue, client_factory=_factory_for(client))  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger="rag.messenger.sender"):
        await sender.dispatch(_payload_text_only(), target="graph_api")

    dispatch_lines = [
        r.getMessage()
        for r in caplog.records
        if "outbound.graph_api dispatch" in r.getMessage()
    ]
    assert dispatch_lines
    assert "image_urls=0" in dispatch_lines[0]
    assert "image_fingerprint=-" in dispatch_lines[0]
