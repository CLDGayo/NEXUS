"""Phase 24 — ``plan_research_node`` decomposition tests.

The planner must:
  * parse well-formed JSON list responses
  * dedupe whitespace-equal entries and drop blanks
  * cap to 3 entries even when the LLM returns more
  * fall back to ``[search_query]`` on JSON parse failure
  * fall back to ``[search_query]`` on LLM error
  * use the fast 8B ``followup_model``
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
        prompt_tokens=20,
        completion_tokens=40,
        total_tokens=60,
        latency_ms=120,
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"calls": 0, "response": "[]"}

    async def fake_chat(messages, *, model, **kwargs):
        box["calls"] += 1
        box["messages"] = messages
        box["model"] = model
        box["kwargs"] = kwargs
        return _result(box["response"])

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)
    return box


@pytest.mark.unit
async def test_plan_parses_well_formed_list(captured: dict[str, Any]) -> None:
    captured["response"] = (
        '["Project Atlas overview", "Project Helios overview", '
        '"comparison of Atlas and Helios outcomes"]'
    )
    state = {"search_query": "compare Atlas and Helios"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == [
        "Project Atlas overview",
        "Project Helios overview",
        "comparison of Atlas and Helios outcomes",
    ]


@pytest.mark.unit
async def test_plan_dedupes_and_drops_blanks(
    captured: dict[str, Any],
) -> None:
    captured["response"] = (
        '["Atlas overview", "  Atlas overview  ", "", "Helios overview"]'
    )
    state = {"search_query": "compare"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["Atlas overview", "Helios overview"]


@pytest.mark.unit
async def test_plan_caps_to_three(captured: dict[str, Any]) -> None:
    captured["response"] = '["one", "two", "three", "four", "five", "six", "seven"]'
    state = {"search_query": "many things"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["one", "two", "three"]


@pytest.mark.unit
async def test_plan_falls_back_on_parse_failure(
    captured: dict[str, Any],
) -> None:
    captured["response"] = "not json at all"
    state = {"search_query": "fallback query text"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["fallback query text"]


@pytest.mark.unit
async def test_plan_falls_back_on_empty_list(
    captured: dict[str, Any],
) -> None:
    captured["response"] = "[]"
    state = {"search_query": "fallback query text"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["fallback query text"]


@pytest.mark.unit
async def test_plan_falls_back_on_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a, **_kw):
        raise LLMError("upstream 502")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", boom)
    state = {"search_query": "fallback query text"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["fallback query text"]


@pytest.mark.unit
async def test_plan_uses_followup_model(captured: dict[str, Any]) -> None:
    captured["response"] = '["a", "b"]'
    state = {"search_query": "anything"}
    await nodes_module.plan_research_node(state)
    assert captured["model"] == settings.followup_model
    assert captured["model"] != settings.generation_model


@pytest.mark.unit
async def test_plan_strips_non_string_entries(
    captured: dict[str, Any],
) -> None:
    """If the LLM emits numbers/objects inside the JSON array, drop them."""

    captured["response"] = '["valid", 42, {"x": 1}, "also valid"]'
    state = {"search_query": "fallback"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["valid", "also valid"]


@pytest.mark.unit
async def test_plan_handles_code_fence_wrapped_json(
    captured: dict[str, Any],
) -> None:
    """Many 8B models wrap JSON in ```json ... ``` fences. Tolerate it."""

    captured["response"] = '```json\n["a", "b"]\n```'
    state = {"search_query": "fallback"}
    out = await nodes_module.plan_research_node(state)
    assert out["sub_queries"] == ["a", "b"]
