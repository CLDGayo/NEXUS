"""Phase 24 / Phase 25 — ``route_query_node`` classifier tests.

The router must:
  * classify ``is_research_mode`` (bool) AND ``query_intent`` (factual |
    conceptual | mixed | None) from a single JSON response
  * tolerate fenced ```` ```json``` ```` envelopes and surrounding prose
  * default to ``(False, None)`` on LLM error, JSON parse failure, or
    unrecognised intent values so the pipeline degrades to pre-Phase-25
    behavior (direct mode, uniform fuse weights)
  * use the fast 8B ``followup_model`` with ``max_tokens >= 64`` so the
    JSON envelope fits cleanly while staying cheap
"""

from __future__ import annotations

import json
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
        completion_tokens=12,
        total_tokens=22,
        latency_ms=12,
    )


def _json_payload(is_research: bool, intent: str | None) -> str:
    body: dict[str, Any] = {"is_research_mode": is_research}
    if intent is not None:
        body["intent"] = intent
    return json.dumps(body)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {
        "calls": 0,
        "response": _json_payload(False, "mixed"),
    }

    async def fake_chat(messages, *, model, **kwargs):
        box["calls"] += 1
        box["messages"] = messages
        box["model"] = model
        box["kwargs"] = kwargs
        return _result(box["response"])

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)
    return box


@pytest.mark.unit
async def test_route_direct_factual(captured: dict[str, Any]) -> None:
    captured["response"] = _json_payload(False, "factual")
    state = {"query": "what is the production VPS IP for nexus?"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": "factual"}
    assert captured["calls"] == 1


@pytest.mark.unit
async def test_route_direct_conceptual(captured: dict[str, Any]) -> None:
    captured["response"] = _json_payload(False, "conceptual")
    state = {"query": "explain the trade-offs of static vs dynamic RRF"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": "conceptual"}


@pytest.mark.unit
async def test_route_research_mixed(captured: dict[str, Any]) -> None:
    captured["response"] = _json_payload(True, "mixed")
    state = {"query": "compare Atlas and Helios across Q1 and Q2"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": True, "query_intent": "mixed"}


@pytest.mark.unit
async def test_route_tolerates_json_fence(captured: dict[str, Any]) -> None:
    captured["response"] = (
        "```json\n"
        '{"is_research_mode": false, "intent": "factual"}\n'
        "```"
    )
    state = {"query": "anything"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": "factual"}


@pytest.mark.unit
async def test_route_tolerates_prose_around_json(
    captured: dict[str, Any],
) -> None:
    captured["response"] = (
        'Here is the classification: '
        '{"is_research_mode": true, "intent": "conceptual"}. Hope this helps.'
    )
    state = {"query": "anything"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": True, "query_intent": "conceptual"}


@pytest.mark.unit
async def test_route_invalid_intent_value_becomes_none(
    captured: dict[str, Any],
) -> None:
    captured["response"] = json.dumps(
        {"is_research_mode": False, "intent": "weird"}
    )
    state = {"query": "anything"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": None}


@pytest.mark.unit
async def test_route_unparseable_defaults(captured: dict[str, Any]) -> None:
    captured["response"] = "I am not sure what you want."
    state = {"query": "what?"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": None}


@pytest.mark.unit
async def test_route_llm_error_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a, **_kw):
        raise LLMError("upstream 502")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", boom)
    state = {"query": "anything"}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": None}


@pytest.mark.unit
async def test_route_uses_followup_model_and_max_tokens(
    captured: dict[str, Any],
) -> None:
    state = {"query": "anything"}
    await nodes_module.route_query_node(state)
    assert captured["model"] == settings.followup_model
    assert captured["model"] != settings.generation_model
    assert captured["kwargs"]["temperature"] == 0.0
    assert captured["kwargs"]["max_tokens"] >= 64


@pytest.mark.unit
async def test_route_prefers_search_query_over_query(
    captured: dict[str, Any],
) -> None:
    """When ``search_query`` is set (post-rewrite), the router must
    classify against the disambiguated string, not the raw query."""

    state = {
        "query": "and then?",
        "search_query": "compare Atlas and Helios",
    }
    captured["response"] = _json_payload(True, "mixed")
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": True, "query_intent": "mixed"}
    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    assert "compare Atlas and Helios" in user_msg["content"]
    assert "and then?" not in user_msg["content"]


@pytest.mark.unit
async def test_route_skips_when_query_blank(
    captured: dict[str, Any],
) -> None:
    state = {"query": "   "}
    out = await nodes_module.route_query_node(state)
    assert out == {"is_research_mode": False, "query_intent": None}
    assert captured["calls"] == 0
