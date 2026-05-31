"""Phase 38 — stateless comment triage engine tests.

Pins ``triage_comment`` behaviour: correct routing for each action,
fail-closed to ``ignore`` on LLM error / bad JSON / bad shape / invalid
action, no LLM call for empty input, and ``"null"`` / empty-string reply
normalisation to ``None``. ``chat_complete`` is always stubbed — these
tests never touch the network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from rag.messenger import triage as _triage
from rag.messenger.triage import TriageResult, triage_comment
from rag.orchestrator.llm import LLMError


def _stub_chat(content: str):
    """Return an async ``chat_complete`` stub yielding ``content``."""

    async def _inner(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(content=content)

    return _inner


@pytest.mark.unit
class TestTriageRouting:
    async def test_public_and_private_inquiry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {
                "action": "public_and_private",
                "public_reply": "Great question! DM sent 💬",
                "private_reply": "Hi! Let me help you find what you need...",
            }
        )
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat(payload))

        result = await triage_comment("how much is the widget?")

        assert isinstance(result, TriageResult)
        assert result.action == "public_and_private"
        assert result.public_reply == "Great question! DM sent 💬"
        assert result.private_reply == "Hi! Let me help you find what you need..."

    async def test_public_only_praise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps(
            {
                "action": "public_only",
                "public_reply": "Thank you so much! 🙌",
                "private_reply": None,
            }
        )
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat(payload))

        result = await triage_comment("I love this brand!")

        assert result.action == "public_only"
        assert result.public_reply == "Thank you so much! 🙌"
        assert result.private_reply is None

    async def test_ignore_spam(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps(
            {"action": "ignore", "public_reply": None, "private_reply": None}
        )
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat(payload))

        result = await triage_comment("@friend check this out lol")

        assert result.action == "ignore"
        assert result.public_reply is None
        assert result.private_reply is None


@pytest.mark.unit
class TestTriageFailClosed:
    async def test_llm_error_returns_ignore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(*_a: Any, **_k: Any) -> SimpleNamespace:
            raise LLMError("proxy 503")

        monkeypatch.setattr(_triage, "chat_complete", _boom)

        result = await triage_comment("anything")

        assert result == TriageResult("ignore", None, None)

    async def test_malformed_json_returns_ignore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat("not json at all{"))

        result = await triage_comment("hello")

        assert result.action == "ignore"

    async def test_non_dict_json_returns_ignore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat("[1, 2, 3]"))

        result = await triage_comment("hello")

        assert result.action == "ignore"

    async def test_invalid_action_returns_ignore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"action": "explode", "public_reply": "x", "private_reply": "y"}
        )
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat(payload))

        result = await triage_comment("hello")

        assert result.action == "ignore"

    async def test_empty_comment_skips_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        async def _track(*_a: Any, **_k: Any) -> SimpleNamespace:
            nonlocal called
            called = True
            return SimpleNamespace(content="{}")

        monkeypatch.setattr(_triage, "chat_complete", _track)

        result = await triage_comment("   ")

        assert result.action == "ignore"
        assert called is False, "empty comment must short-circuit before the LLM"

    async def test_null_string_replies_normalized_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {
                "action": "public_only",
                "public_reply": "null",
                "private_reply": "",
            }
        )
        monkeypatch.setattr(_triage, "chat_complete", _stub_chat(payload))

        result = await triage_comment("hello")

        assert result.public_reply is None
        assert result.private_reply is None
