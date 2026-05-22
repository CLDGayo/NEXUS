"""Phase 22 — ``rewrite_query_node`` coreference resolution tests.

The rewriter must:
  * skip the LLM call entirely on first turn (empty history),
  * skip when query is empty,
  * resolve affirmations like "yes please" using the assistant's prior
    turn as antecedent,
  * pass the original query through unchanged when the LLM raises,
  * (Phase 22.2) write the rewrite to ``search_query`` so retrieval gets
    the disambiguated string while ``query`` stays the user's natural
    phrasing for the generation LLM.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from typing import Any

import pytest

from rag.config import settings
from rag.orchestrator import nodes as nodes_module
from rag.orchestrator.llm import LLMError, LLMResult


def _result(content: str) -> LLMResult:
    return LLMResult(
        content=content,
        model=settings.followup_model,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=12,
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``chat_complete`` so tests can inspect the messages + model
    the rewriter sends, and inject a canned response."""

    box: dict[str, Any] = {"calls": 0, "response": "rewritten query"}

    async def fake_chat(messages, *, model, **kwargs):
        box["calls"] += 1
        box["messages"] = messages
        box["model"] = model
        box["kwargs"] = kwargs
        return _result(box["response"])

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)
    return box


@pytest.mark.unit
async def test_rewrite_skips_when_history_empty(
    captured: dict[str, Any],
) -> None:
    state = {"query": "what is project Atlas?", "history": []}
    out = await nodes_module.rewrite_query_node(state)
    assert out == {}
    assert captured["calls"] == 0


@pytest.mark.unit
async def test_rewrite_skips_when_history_missing(
    captured: dict[str, Any],
) -> None:
    state = {"query": "what is project Atlas?"}
    out = await nodes_module.rewrite_query_node(state)
    assert out == {}
    assert captured["calls"] == 0


@pytest.mark.unit
async def test_rewrite_skips_when_query_blank(
    captured: dict[str, Any],
) -> None:
    state = {
        "query": "   ",
        "history": [{"role": "assistant", "content": "Want a summary?"}],
    }
    out = await nodes_module.rewrite_query_node(state)
    assert out == {}
    assert captured["calls"] == 0


@pytest.mark.unit
async def test_rewrite_resolves_yes_please(captured: dict[str, Any]) -> None:
    captured["response"] = "summary of project Atlas"
    state = {
        "query": "yes please",
        "history": [
            {"role": "user", "content": "Tell me about project Atlas"},
            {
                "role": "assistant",
                "content": "Atlas is our 2026 platform — want a summary?",
            },
        ],
    }
    out = await nodes_module.rewrite_query_node(state)
    # Phase 22.2 — rewrite goes to ``search_query``; ``query`` is
    # untouched so the generation LLM still hears the user verbatim.
    assert out == {"search_query": "summary of project Atlas"}
    assert "query" not in out
    assert state["query"] == "yes please"
    assert captured["calls"] == 1
    assert captured["model"] == settings.followup_model
    assert captured["kwargs"]["temperature"] == 0.0


@pytest.mark.unit
async def test_rewrite_passthrough_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a, **_kw):
        raise LLMError("upstream 502")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", boom)

    state = {
        "query": "yes please",
        "history": [{"role": "assistant", "content": "Want me to summarize?"}],
    }
    out = await nodes_module.rewrite_query_node(state)
    assert out == {}


@pytest.mark.unit
async def test_rewrite_drops_blank_llm_response(
    captured: dict[str, Any],
) -> None:
    captured["response"] = "   "  # whitespace-only
    state = {
        "query": "yes",
        "history": [{"role": "assistant", "content": "Want me to summarize?"}],
    }
    out = await nodes_module.rewrite_query_node(state)
    assert out == {}


@pytest.mark.unit
async def test_rewrite_uses_fast_followup_model(
    captured: dict[str, Any],
) -> None:
    state = {
        "query": "yes please",
        "history": [{"role": "assistant", "content": "Want a summary?"}],
    }
    await nodes_module.rewrite_query_node(state)
    # Phase 22 requirement: rewriter must use the fast 8B model, NOT the
    # main 70B generation model, to keep multi-turn latency in budget.
    assert captured["model"] == settings.followup_model
    assert captured["model"] != settings.generation_model
