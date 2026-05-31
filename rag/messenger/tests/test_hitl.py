"""Phase 37 — Unit tests for rag.messenger.hitl.

Uses the autouse ``fake_redis`` + ``stub_tenant_resolution`` fixtures
from conftest.py. HTTP is mocked via ``unittest.mock.patch`` on
``rag.messenger.hitl.httpx.AsyncClient``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rag.config import settings
from rag.messenger.hitl import (
    clear_bot_paused,
    is_bot_paused,
    is_human_echo,
    is_read_event,
    notify_owner_if_needed,
    set_bot_paused,
)


# ---------------------------------------------------------------------------
# Pure-function helpers (no Redis, no HTTP)
# ---------------------------------------------------------------------------


class TestIsReadEvent:
    def test_read_event_present(self) -> None:
        assert is_read_event({"read": {"watermark": 123}}) is True

    def test_read_event_absent(self) -> None:
        assert is_read_event({"message": {"text": "hi"}}) is False

    def test_empty_event(self) -> None:
        assert is_read_event({}) is False


class TestIsHumanEcho:
    def test_no_app_id_means_human(self) -> None:
        event = {"message": {"is_echo": True, "text": "hi"}}
        assert is_human_echo(event, our_app_id="111") is True

    def test_different_app_id_means_human(self) -> None:
        event = {"message": {"is_echo": True, "app_id": 222, "text": "hi"}}
        assert is_human_echo(event, our_app_id="111") is True

    def test_matching_app_id_is_bot(self) -> None:
        event = {"message": {"is_echo": True, "app_id": "111", "text": "hi"}}
        assert is_human_echo(event, our_app_id="111") is False

    def test_not_an_echo(self) -> None:
        event = {"message": {"text": "hi"}}
        assert is_human_echo(event, our_app_id="111") is False

    def test_no_message_at_all(self) -> None:
        assert is_human_echo({}, our_app_id="111") is False

    def test_our_app_id_none_preserves_legacy_behaviour(self) -> None:
        # Pre-Phase-37 behaviour: without MESSENGER_APP_ID configured we
        # cannot discriminate bot vs human echoes, so we MUST return False
        # (so the existing ``is_echo`` filter in the webhook router keeps
        # silently dropping every echo — no false pauses).
        event = {"message": {"is_echo": True}}
        assert is_human_echo(event, our_app_id=None) is False
        event_with_app_id = {"message": {"is_echo": True, "app_id": 999}}
        assert is_human_echo(event_with_app_id, our_app_id=None) is False


# ---------------------------------------------------------------------------
# Pause state (Redis-backed)
# ---------------------------------------------------------------------------


class TestBotPauseState:
    @pytest.mark.asyncio
    async def test_default_not_paused(self) -> None:
        assert await is_bot_paused("u1") is False

    @pytest.mark.asyncio
    async def test_set_then_is_paused(self) -> None:
        await set_bot_paused("u1")
        assert await is_bot_paused("u1") is True
        assert await is_bot_paused("u2") is False

    @pytest.mark.asyncio
    async def test_clear_releases_pause(self) -> None:
        await set_bot_paused("u1")
        await clear_bot_paused("u1")
        assert await is_bot_paused("u1") is False

    @pytest.mark.asyncio
    async def test_empty_sender_id_short_circuits(self, fake_redis: Any) -> None:
        # Empty sender should never touch Redis nor leak truthy state.
        assert await is_bot_paused("") is False
        await set_bot_paused("")
        await clear_bot_paused("")
        # No keys created.
        keys = await fake_redis.keys("nexus:hitl:paused:*")
        assert keys == []

    @pytest.mark.asyncio
    async def test_pause_ttl_respects_settings(
        self, monkeypatch: pytest.MonkeyPatch, fake_redis: Any
    ) -> None:
        monkeypatch.setattr(settings, "hitl_pause_duration_s", 90)
        await set_bot_paused("u1")
        ttl = await fake_redis.ttl("nexus:hitl:paused:u1")
        # fakeredis returns the TTL we set, within 1s of jitter.
        assert 80 <= ttl <= 90


# ---------------------------------------------------------------------------
# notify_owner_if_needed (Redis SET-NX + httpx)
# ---------------------------------------------------------------------------


def _mock_httpx_client(*, status_code: int = 200) -> tuple[MagicMock, MagicMock]:
    """Build a MagicMock AsyncClient class that yields a recordable post."""

    response = MagicMock()
    response.status_code = status_code
    response.text = "ok"
    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "boom", request=MagicMock(), response=response
            )
        )
    else:
        response.raise_for_status = MagicMock(return_value=None)

    post = AsyncMock(return_value=response)
    instance = MagicMock()
    instance.post = post
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    cls = MagicMock(return_value=instance)
    return cls, post


class TestNotifyOwnerIfNeeded:
    @pytest.mark.asyncio
    async def test_unset_webhook_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "n8n_webhook_notify_url", None)
        sent = await notify_owner_if_needed(
            sender_id="u1",
            page_id="p1",
            thread_key="u1",
            user_query="hi",
            bot_answer="hello",
        )
        assert sent is False

    @pytest.mark.asyncio
    async def test_empty_sender_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings, "n8n_webhook_notify_url", "https://example.test/n8n"
        )
        sent = await notify_owner_if_needed(
            sender_id="",
            page_id="p1",
            thread_key="",
            user_query="hi",
            bot_answer="hello",
        )
        assert sent is False

    @pytest.mark.asyncio
    async def test_first_call_fires_and_payload_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings, "n8n_webhook_notify_url", "https://example.test/n8n"
        )
        cls, post = _mock_httpx_client(status_code=200)
        with patch("rag.messenger.hitl.httpx.AsyncClient", cls):
            sent = await notify_owner_if_needed(
                sender_id="u1",
                page_id="p1",
                thread_key="u1",
                user_query="hi",
                bot_answer="hello",
            )
        assert sent is True
        assert post.await_count == 1
        kwargs = post.await_args.kwargs
        assert kwargs["json"] == {
            "sender_id": "u1",
            "page_id": "p1",
            "thread_key": "u1",
            "user_query": "hi",
            "bot_answer": "hello",
        }
        # Posted to the configured URL.
        assert post.await_args.args[0] == "https://example.test/n8n"

    @pytest.mark.asyncio
    async def test_second_call_dedupes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            settings, "n8n_webhook_notify_url", "https://example.test/n8n"
        )
        cls, post = _mock_httpx_client(status_code=200)
        with patch("rag.messenger.hitl.httpx.AsyncClient", cls):
            first = await notify_owner_if_needed(
                sender_id="u1",
                page_id="p1",
                thread_key="u1",
                user_query="q1",
                bot_answer="a1",
            )
            second = await notify_owner_if_needed(
                sender_id="u1",
                page_id="p1",
                thread_key="u1",
                user_query="q2",
                bot_answer="a2",
            )
        assert first is True
        assert second is False
        # Only one POST was actually made — second call was SET-NX dedup.
        assert post.await_count == 1

    @pytest.mark.asyncio
    async def test_http_500_returns_false_but_keeps_flag(
        self, monkeypatch: pytest.MonkeyPatch, fake_redis: Any
    ) -> None:
        # On HTTP failure we still consider the session "claimed" — we
        # don't want a transient n8n outage to drown the owner in retries
        # on every subsequent turn. The flag persists (TTL 24h).
        monkeypatch.setattr(
            settings, "n8n_webhook_notify_url", "https://example.test/n8n"
        )
        cls, _post = _mock_httpx_client(status_code=500)
        with patch("rag.messenger.hitl.httpx.AsyncClient", cls):
            sent = await notify_owner_if_needed(
                sender_id="u1",
                page_id="p1",
                thread_key="u1",
                user_query="hi",
                bot_answer="hello",
            )
        assert sent is False
        # SET-NX claim was made before the POST.
        assert await fake_redis.exists("nexus:hitl:notified:u1") == 1

    @pytest.mark.asyncio
    async def test_payload_caps_long_strings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            settings, "n8n_webhook_notify_url", "https://example.test/n8n"
        )
        cls, post = _mock_httpx_client(status_code=200)
        long_query = "Q" * 2000
        long_answer = "A" * 5000
        with patch("rag.messenger.hitl.httpx.AsyncClient", cls):
            await notify_owner_if_needed(
                sender_id="u1",
                page_id="p1",
                thread_key="u1",
                user_query=long_query,
                bot_answer=long_answer,
            )
        json_body = post.await_args.kwargs["json"]
        assert len(json_body["user_query"]) == 500
        assert len(json_body["bot_answer"]) == 1000
