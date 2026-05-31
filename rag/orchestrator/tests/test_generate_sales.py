"""Phase 33 — `generate_node` tool-binding + execution loop tests.

Surface-gated: tool injection + SDR overlay must only fire for
``surface == "messenger"``. SPA path stays identical to the prior
behavior so all Phase 17/22 tests in ``test_generate_multimodal.py``
keep passing.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from types import SimpleNamespace
from typing import Any

import pytest

from rag.orchestrator import nodes as nodes_module
from rag.orchestrator import sales_tools as st
from rag.orchestrator.llm import LLMError, LLMResult
from rag.retrieval.types import ScoredChunk


def _stub_enriched(name: str = "Luffy Gear 4 Bound man") -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _chunk(idx: int) -> ScoredChunk:
    return ScoredChunk(
        id=f"c-{idx}",
        text="our plan starts at $99 per month including onboarding",
        score=1.0 / idx,
        metadata={"title": f"Note {idx}"},
    )


def _state(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "query": "Do you have Luffy Gear 4 in stock?",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "messenger",
        "tenant_id": "acme",
        "reranked": [_chunk(1), _chunk(2)],
    }
    base.update(extra)
    return base


def _llm_text(content: str = "Answer grounded in [1].") -> LLMResult:
    return LLMResult(
        content=content,
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        latency_ms=1,
    )


def _llm_tools(
    tool_calls: list[dict[str, Any]],
    content: str = "",
) -> LLMResult:
    return LLMResult(
        content=content,
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        latency_ms=1,
        tool_calls=tool_calls,
    )


# ---------------------------------------------------------------------------
# Surface gating: Messenger gets tools + SDR overlay; SPA does not.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_messenger_surface_binds_tools_and_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    await nodes_module.generate_node(_state())

    assert captured["kwargs"].get("extra") == {
        "tools": st.SALES_TOOLS_SCHEMA,
        "tool_choice": "auto",
    }
    system_content = captured["messages"][0]["content"]
    assert "--- SALES REPRESENTATIVE MODE ---" in system_content


@pytest.mark.unit
async def test_spa_surface_omits_tools_and_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    await nodes_module.generate_node(_state(surface="spa"))

    assert captured["kwargs"].get("extra") is None
    system_content = captured["messages"][0]["content"]
    assert "--- SALES REPRESENTATIVE MODE ---" not in system_content


@pytest.mark.unit
async def test_messenger_multimodal_keeps_overlay_but_strips_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 33.1 — vision/multimodal path on Messenger keeps the SDR
    persona overlay (already injected into ``system_content``) but must
    NOT pass ``extra={"tools": ...}`` to ``chat_complete()``. Vision
    models mix ``image_url`` content arrays with ``tools`` unreliably
    across providers; binding tools here was a latent intermittent bug."""
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    state = _state(
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    # Vision overlay AND SDR overlay both injected exactly once.
    assert "--- IMAGE QUERY INSTRUCTIONS ---" in system_content
    assert system_content.count("--- SALES REPRESENTATIVE MODE ---") == 1
    # Phase 33.1 — tools stripped on the vision path.
    assert captured["kwargs"].get("extra") is None
    # Sanity: tool schema is still importable (no accidental rename).
    assert st.SALES_TOOLS_SCHEMA[0]["function"]["name"] == "check_inventory"


# ---------------------------------------------------------------------------
# Tool-call execution loop.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tool_loop_executes_once_then_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}
    tool_calls_seen: list[dict[str, Any]] = []

    tool_call = {
        "id": "tc-1",
        "type": "function",
        "function": {
            "name": "check_inventory",
            "arguments": '{"product_name": "Luffy Gear 4"}',
        },
    }

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _llm_tools([tool_call])
        return _llm_text("We have 5 in stock — want me to send a checkout link? [1]")

    async def fake_exec(tc: dict[str, Any], *, tenant_id: str) -> dict[str, str]:
        tool_calls_seen.append(tc)
        assert tenant_id == "acme"
        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": "- Luffy Gear 4: USD 129.99, 5 available (In stock)",
        }

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)
    monkeypatch.setattr(nodes_module, "execute_tool_call", fake_exec)

    result = await nodes_module.generate_node(_state())

    assert call_count["n"] == 2
    assert len(tool_calls_seen) == 1
    assert tool_calls_seen[0]["id"] == "tc-1"
    assert "checkout link" in result["answer"]
    assert result["abstained"] is False


@pytest.mark.unit
async def test_tool_loop_caps_at_three_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}
    final_text = "Final answer after cap [1]."

    tool_call = {
        "id": "tc-loop",
        "type": "function",
        "function": {
            "name": "check_inventory",
            "arguments": '{"product_name": "X"}',
        },
    }

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        call_count["n"] += 1
        # Always returns tool_calls until the cap forces exit; the loop
        # condition then breaks and the LAST result's content is what
        # generate_node returns.
        return _llm_tools([tool_call], content=final_text)

    async def fake_exec(tc: dict[str, Any], *, tenant_id: str) -> dict[str, str]:
        return {"role": "tool", "tool_call_id": tc["id"], "content": "OK"}

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)
    monkeypatch.setattr(nodes_module, "execute_tool_call", fake_exec)

    result = await nodes_module.generate_node(_state())

    # 1 initial + 3 follow-ups = 4 chat_complete calls; loop then exits
    # because tool_loop hit _tool_loop_max (3).
    assert call_count["n"] == 4
    assert result["answer"] == final_text
    assert result["abstained"] is False


# ---------------------------------------------------------------------------
# Phase 33.3 — Continuity note injection.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_messenger_continuity_note_fires_when_history_mentions_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    state = _state(
        history=[
            {"role": "user", "content": "do you have luffy?"},
            {
                "role": "assistant",
                "content": "Yes — Luffy Gear 4 Bound man is JPY 2,100.",
            },
        ],
        _enriched_products=[_stub_enriched()],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "[Continuity Note:" in system_content


@pytest.mark.unit
async def test_messenger_continuity_note_absent_when_history_lacks_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Greeting-only prior turn → no continuity note even with assistant turn."""
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    state = _state(
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello! How can I help?"},
        ],
        _enriched_products=[_stub_enriched()],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "[Continuity Note:" not in system_content


@pytest.mark.unit
async def test_messenger_continuity_note_absent_on_first_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    await nodes_module.generate_node(_state())  # no history, no _enriched_products

    system_content = captured["messages"][0]["content"]
    assert "[Continuity Note:" not in system_content


@pytest.mark.unit
async def test_spa_surface_never_gets_continuity_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    state = _state(
        surface="spa",
        history=[
            {"role": "user", "content": "luffy?"},
            {"role": "assistant", "content": "Luffy Gear 4 Bound man, JPY 2,100."},
        ],
        _enriched_products=[_stub_enriched()],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "[Continuity Note:" not in system_content


@pytest.mark.unit
async def test_messenger_vision_continuity_note_fires_with_history_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vision path on Messenger also gets the continuity hint."""
    captured: dict[str, Any] = {}

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        captured["messages"] = messages
        return _llm_text()

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)

    state = _state(
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
        history=[
            {"role": "user", "content": "is this luffy?"},
            {
                "role": "assistant",
                "content": "Yes — Luffy Gear 4 Bound man, JPY 2,100.",
            },
        ],
        _enriched_products=[_stub_enriched()],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "[Continuity Note:" in system_content


@pytest.mark.unit
async def test_tool_followup_llm_error_abstains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}
    tool_call = {
        "id": "tc-err",
        "type": "function",
        "function": {
            "name": "check_inventory",
            "arguments": '{"product_name": "X"}',
        },
    }

    async def fake_chat(messages: list[dict[str, Any]], **kwargs: Any) -> LLMResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _llm_tools([tool_call])
        raise LLMError("upstream 502")

    async def fake_exec(tc: dict[str, Any], *, tenant_id: str) -> dict[str, str]:
        return {"role": "tool", "tool_call_id": tc["id"], "content": "OK"}

    monkeypatch.setattr(nodes_module, "chat_complete", fake_chat)
    monkeypatch.setattr(nodes_module, "execute_tool_call", fake_exec)

    result = await nodes_module.generate_node(_state())

    assert result["abstained"] is True
    assert result["requires_human_handover"] is True
    assert "tool followup llm error" in result["handover_reason"]
