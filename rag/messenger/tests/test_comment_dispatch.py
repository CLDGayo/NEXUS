"""Phase 38 — comment dispatch + feed-webhook wiring tests.

Two surfaces:

1. The standalone Graph API v21.0 dispatchers ``send_public_comment_reply``
   / ``send_private_reply`` — fail-silent (200 → True, 400 → False,
   transport error → False), correct URL + token + body.
2. The feed-event branch in ``messenger_inbound_direct`` — schedules the
   triage background task for a real comment, honours the page echo guard,
   stays dormant when the feature flag is off or the comment is empty, and
   dispatches both public + private replies on a ``public_and_private``
   verdict.

No network: httpx and ``triage_comment`` are stubbed throughout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from rag import messenger_overlay
from rag.config import settings as _settings
from rag.main import app
from rag.messenger import sender as _sender
from rag.messenger.routers import webhook as _webhook
from rag.messenger.routers.webhook import (
    get_graph_runner,
    get_outbound_sender,
    set_event_scheduler,
)
from rag.messenger.sender import send_private_reply, send_public_comment_reply
from rag.messenger.triage import TriageResult


# ---------------------------------------------------------------------------
# Dispatcher tests — httpx stub
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _StubClient:
    """Mimics ``httpx.AsyncClient`` for a single POST; records the call."""

    def __init__(
        self, *, resp: _Resp | None = None, exc: Exception | None = None
    ) -> None:
        self._resp = resp
        self._exc = exc
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(
        self, url: str, *, params: dict[str, Any], json: dict[str, Any]
    ) -> _Resp:
        self.posts.append({"url": url, "params": params, "json": json})
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


def _patch_client(monkeypatch: pytest.MonkeyPatch, stub: _StubClient) -> None:
    monkeypatch.setattr(_sender.httpx, "AsyncClient", lambda *_a, **_k: stub)


@pytest.mark.unit
class TestPublicCommentReply:
    async def test_200_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _StubClient(resp=_Resp(200))
        _patch_client(monkeypatch, stub)

        ok = await send_public_comment_reply(
            comment_id="c_1", message="thanks!", access_token="tok"
        )

        assert ok is True
        assert len(stub.posts) == 1
        post = stub.posts[0]
        assert post["url"] == "https://graph.facebook.com/v21.0/c_1/comments"
        assert post["params"] == {"access_token": "tok"}
        assert post["json"] == {"message": "thanks!"}

    async def test_400_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _StubClient(resp=_Resp(400, text="(#100) bad"))
        _patch_client(monkeypatch, stub)

        ok = await send_public_comment_reply(
            comment_id="c_1", message="x", access_token="tok"
        )

        assert ok is False

    async def test_transport_error_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubClient(exc=httpx.ConnectError("refused"))
        _patch_client(monkeypatch, stub)

        ok = await send_public_comment_reply(
            comment_id="c_1", message="x", access_token="tok"
        )

        assert ok is False


@pytest.mark.unit
class TestPrivateReply:
    async def test_200_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _StubClient(resp=_Resp(200))
        _patch_client(monkeypatch, stub)

        ok = await send_private_reply(
            comment_id="c_9", message="DM body", access_token="tok"
        )

        assert ok is True
        post = stub.posts[0]
        assert post["url"] == "https://graph.facebook.com/v21.0/c_9/private_replies"
        assert post["json"] == {"message": "DM body"}

    async def test_stale_400_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Meta error (#10900): comment older than 7 days — logged, dropped.
        stub = _StubClient(resp=_Resp(400, text="(#10900) too old"))
        _patch_client(monkeypatch, stub)

        ok = await send_private_reply(comment_id="c_9", message="x", access_token="tok")

        assert ok is False

    async def test_transport_error_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _StubClient(exc=httpx.ReadTimeout("slow"))
        _patch_client(monkeypatch, stub)

        ok = await send_private_reply(comment_id="c_9", message="x", access_token="tok")

        assert ok is False


# ---------------------------------------------------------------------------
# Feed-webhook wiring tests
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _feed_envelope(
    *,
    comment_id: str = "c_1",
    post_id: str = "p_1",
    message: str = "how much is the widget?",
    from_id: str = "user_77",
    page_id: str = "page_1",
    verb: str = "add",
    item: str = "comment",
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1731742800,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": item,
                            "verb": verb,
                            "comment_id": comment_id,
                            "post_id": post_id,
                            "message": message,
                            "from": {"id": from_id, "name": "Test User"},
                            "created_time": 1731742800,
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def captured_events():
    """Capture scheduled background coroutines instead of firing them."""

    pending: list[Awaitable[None]] = []

    def _sync_scheduler(coro: Awaitable[None]) -> None:
        pending.append(coro)

    set_event_scheduler(_sync_scheduler)
    try:
        yield pending
    finally:
        set_event_scheduler(None)
        # Close any coroutine the test chose not to drain — no warnings.
        for coro in pending:
            close = getattr(coro, "close", None)
            if close is not None:
                close()


@pytest.fixture
def client() -> TestClient:
    """TestClient with trivial graph/sender overrides — the feed path uses
    neither, but the endpoint declares them as dependencies."""

    async def _runner_override() -> object:
        return object()

    async def _sender_override() -> object:
        return object()

    app.dependency_overrides[get_graph_runner] = _runner_override
    app.dependency_overrides[get_outbound_sender] = _sender_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_graph_runner, None)
        app.dependency_overrides.pop(get_outbound_sender, None)


@pytest.fixture
def overlay_tmp(tmp_path, monkeypatch):
    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)
    return messenger_overlay


@pytest.mark.unit
class TestFeedWebhook:
    def test_comment_schedules_triage(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setattr(_settings, "comment_triage_enabled", True)
        # Phase 57: disable automations so the legacy inline-triage path runs.
        monkeypatch.setattr(_settings, "fb_automations_enabled", False)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "feed-secret-1")

        seen: list[str] = []

        async def _stub_triage(text: str) -> TriageResult:
            seen.append(text)
            return TriageResult("ignore", None, None)

        monkeypatch.setattr(_webhook, "triage_comment", _stub_triage)

        body = json.dumps(_feed_envelope(message="how much?")).encode()
        sig = _sign(body, "feed-secret-1")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert len(captured_events) == 1

        import asyncio

        asyncio.run(captured_events[0])
        assert seen == ["how much?"]

    def test_echo_guard_skips_own_page_comment(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setattr(_settings, "comment_triage_enabled", True)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "feed-secret-2")

        # Comment author id == page id → the Page commented on itself.
        body = json.dumps(_feed_envelope(from_id="page_1", page_id="page_1")).encode()
        sig = _sign(body, "feed-secret-2")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert captured_events == []

    def test_flag_off_skips_comment(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setattr(_settings, "comment_triage_enabled", False)
        # Phase 57: disable automations too so that both comment paths are off
        # and the comment is truly dropped (the original intent of this test).
        monkeypatch.setattr(_settings, "fb_automations_enabled", False)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "feed-secret-3")

        body = json.dumps(_feed_envelope()).encode()
        sig = _sign(body, "feed-secret-3")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert captured_events == []

    def test_empty_message_skips_comment(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setattr(_settings, "comment_triage_enabled", True)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "feed-secret-4")

        body = json.dumps(_feed_envelope(message="   ")).encode()
        sig = _sign(body, "feed-secret-4")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert captured_events == []

    def test_public_and_private_dispatches_both(
        self,
        client: TestClient,
        overlay_tmp,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list[Awaitable[None]],
    ) -> None:
        monkeypatch.setattr(_settings, "comment_triage_enabled", True)
        # Phase 57: disable automations so the legacy inline-triage path runs.
        monkeypatch.setattr(_settings, "fb_automations_enabled", False)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "feed-secret-5")
        overlay_tmp.set_page_access_token("EAA-feed-token-123456")

        async def _stub_triage(_text: str) -> TriageResult:
            return TriageResult(
                "public_and_private",
                public_reply="DM sent 💬",
                private_reply="Hi! Let me help.",
            )

        monkeypatch.setattr(_webhook, "triage_comment", _stub_triage)

        pub = AsyncMock(return_value=True)
        priv = AsyncMock(return_value=True)
        monkeypatch.setattr(_sender, "send_public_comment_reply", pub)
        monkeypatch.setattr(_sender, "send_private_reply", priv)

        body = json.dumps(_feed_envelope(comment_id="c_42")).encode()
        sig = _sign(body, "feed-secret-5")

        r = client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert r.status_code == 200
        assert len(captured_events) == 1

        import asyncio

        asyncio.run(captured_events[0])

        pub.assert_awaited_once()
        assert pub.await_args.kwargs["comment_id"] == "c_42"
        assert pub.await_args.kwargs["message"] == "DM sent 💬"
        priv.assert_awaited_once()
        assert priv.await_args.kwargs["comment_id"] == "c_42"
        assert priv.await_args.kwargs["message"] == "Hi! Let me help."
