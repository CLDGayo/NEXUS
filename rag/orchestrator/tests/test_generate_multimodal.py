"""Phase 15 — `generate_node` multimodal routing tests.

Each test stubs `chat_complete` to capture the messages + model the node
sends to LiteLLM, then asserts the multimodal-vs-text branching is correct.
"""

from __future__ import annotations

import logging
import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from typing import Any

import pytest

from rag.config import settings
from rag.orchestrator import nodes as nodes_module
from rag.orchestrator.llm import LLMError, LLMResult
from rag.retrieval.types import ScoredChunk


def _chunk(idx: int) -> ScoredChunk:
    return ScoredChunk(
        id=f"c-{idx}",
        text="our plan starts at $99 per month including onboarding",
        score=1.0 / idx,
        metadata={"title": f"Note {idx}"},
    )


def _state(**extra: Any) -> dict:
    base: dict[str, Any] = {
        "query": "What is shown here?",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "spa",
        "reranked": [_chunk(1), _chunk(2)],
    }
    base.update(extra)
    return base


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch chat_complete to record what generate_node sent."""

    box: dict[str, Any] = {}

    async def fake_chat(messages, *, model, **kwargs):
        box["messages"] = messages
        box["model"] = model
        box["kwargs"] = kwargs
        return LLMResult(
            content="Answer grounded in [1].",
            model=model,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=12,
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)
    return box


@pytest.mark.unit
async def test_generate_text_only_path_unchanged(captured: dict[str, Any]) -> None:
    result = await nodes_module.generate_node(_state())

    assert captured["model"] == settings.generation_model
    assert captured["messages"] == [
        {"role": "system", "content": captured["messages"][0]["content"]}
    ]
    assert isinstance(captured["messages"][0]["content"], str)
    assert "What is shown here?" in captured["messages"][0]["content"]
    assert result["abstained"] is False


@pytest.mark.unit
async def test_generate_with_image_splits_system_and_user(
    captured: dict[str, Any],
) -> None:
    state = _state(
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}]
    )
    await nodes_module.generate_node(state)

    assert captured["model"] == settings.vision_model
    messages = captured["messages"]
    assert len(messages) == 2

    system_msg, user_msg = messages
    assert system_msg["role"] == "system"
    assert isinstance(system_msg["content"], str)
    assert "(see user message below)" in system_msg["content"]

    assert user_msg["role"] == "user"
    parts = user_msg["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "What is shown here?"}
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,AAA"},
    }


@pytest.mark.unit
async def test_generate_ignores_non_image_attachments(
    captured: dict[str, Any],
) -> None:
    state = _state(
        attachments=[
            {"type": "file", "url": "https://x/y.pdf"},
            {"type": "audio", "url": "https://x/a.mp3"},
        ]
    )
    await nodes_module.generate_node(state)

    # No images survived; falls back to text-only path.
    assert captured["model"] == settings.generation_model
    assert len(captured["messages"]) == 1


@pytest.mark.unit
async def test_generate_skips_image_with_empty_url(
    captured: dict[str, Any],
) -> None:
    state = _state(attachments=[{"type": "image", "url": ""}])
    await nodes_module.generate_node(state)

    assert captured["model"] == settings.generation_model
    assert len(captured["messages"]) == 1


@pytest.mark.unit
async def test_generate_truncates_to_vision_max_attachments(
    captured: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "vision_max_attachments", 2, raising=False)
    state = _state(
        attachments=[
            {"type": "image", "url": f"data:image/png;base64,{i}"}
            for i in range(5)
        ]
    )
    await nodes_module.generate_node(state)

    parts = captured["messages"][1]["content"]
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == 2


@pytest.mark.unit
async def test_generate_vision_llm_error_abstains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a, **_kw):
        raise LLMError("upstream proxy 502")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", boom)

    state = _state(
        attachments=[{"type": "image", "url": "data:image/png;base64,AA"}]
    )
    result = await nodes_module.generate_node(state)

    assert result["abstained"] is True
    assert result["requires_human_handover"] is True
    assert "llm error" in result["handover_reason"]


# ---------------------------------------------------------------------------
# Phase 17 — vision intent overlay tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_vision_intent_messenger_overlay(
    captured: dict[str, Any],
) -> None:
    """Messenger + image → system prompt contains the customer-service overlay."""
    state = _state(
        surface="messenger",
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "--- IMAGE QUERY INSTRUCTIONS ---" in system_content
    assert "pleasant customer service representative" in system_content
    # Must NOT contain the SPA structured sections.
    assert "**Source Document:**" not in system_content


@pytest.mark.unit
async def test_vision_intent_spa_overlay(
    captured: dict[str, Any],
) -> None:
    """SPA + image → system prompt contains the structured-response overlay."""
    state = _state(
        surface="spa",
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "--- IMAGE QUERY INSTRUCTIONS ---" in system_content
    assert "**Source Document:**" in system_content
    assert "**Identified Subject:**" in system_content
    assert "**Related Topics:**" in system_content
    # Must NOT contain the Messenger customer-service phrasing.
    assert "pleasant customer service representative" not in system_content


@pytest.mark.unit
async def test_no_vision_overlay_without_images(
    captured: dict[str, Any],
) -> None:
    """Text-only query → no vision overlay injected."""
    state = _state(surface="spa")
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "--- IMAGE QUERY INSTRUCTIONS ---" not in system_content


# ---------------------------------------------------------------------------
# Phase 22 — history injection into generate_node
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_history_injected_into_text_path(
    captured: dict[str, Any],
) -> None:
    """Prior turns must appear as separate role messages so the LLM sees
    real conversational context, not just a stuffed system prompt."""

    state = _state(
        surface="spa",
        history=[
            {"role": "user", "content": "Tell me about Atlas", "timestamp": 1.0},
            {
                "role": "assistant",
                "content": "Atlas is our 2026 platform.",
                "timestamp": 2.0,
            },
        ],
    )
    await nodes_module.generate_node(state)

    messages = captured["messages"]
    # System + 2 history turns.
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "Tell me about Atlas"}
    assert messages[2] == {
        "role": "assistant",
        "content": "Atlas is our 2026 platform.",
    }


@pytest.mark.unit
async def test_history_strips_timestamp_before_llm(
    captured: dict[str, Any],
) -> None:
    """Timestamps live on disk only — the LLM must never see them."""

    state = _state(
        surface="spa",
        history=[
            {"role": "user", "content": "earlier", "timestamp": 999.0},
        ],
    )
    await nodes_module.generate_node(state)

    for msg in captured["messages"][1:]:
        assert "timestamp" not in msg


@pytest.mark.unit
async def test_history_injected_into_multimodal_path(
    captured: dict[str, Any],
) -> None:
    """When images are attached, history sits between system and the
    final multimodal user turn."""

    state = _state(
        surface="messenger",
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
        history=[
            {"role": "user", "content": "prior question", "timestamp": 1.0},
            {"role": "assistant", "content": "prior answer", "timestamp": 2.0},
        ],
    )
    await nodes_module.generate_node(state)

    messages = captured["messages"]
    # System + 2 history + final multimodal user turn.
    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "prior question"}
    assert messages[2] == {"role": "assistant", "content": "prior answer"}
    assert messages[3]["role"] == "user"
    assert isinstance(messages[3]["content"], list)
    # Final multimodal turn carries the current query + image.
    parts = messages[3]["content"]
    assert parts[0] == {"type": "text", "text": "What is shown here?"}
    assert any(p.get("type") == "image_url" for p in parts)


# ---------------------------------------------------------------------------
# Phase 22.2 — generate_node must read the ORIGINAL ``query`` even when
# ``search_query`` was set by the rewrite/vision nodes. Otherwise the LLM
# echoes the robotic search string and produces third-person summaries.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_text_path_uses_query_not_search_query(
    captured: dict[str, Any],
) -> None:
    state = _state(
        query="what are his projects?",
        search_query="Clarence Gayo projects list",
    )
    await nodes_module.generate_node(state)

    system_content = captured["messages"][0]["content"]
    assert "what are his projects?" in system_content
    assert "Clarence Gayo projects list" not in system_content


@pytest.mark.unit
async def test_generate_multimodal_path_uses_query_not_search_query(
    captured: dict[str, Any],
) -> None:
    state = _state(
        query="who is this?",
        search_query="who is this?\n[Image Analysis: man in suit]",
        attachments=[{"type": "image", "url": "data:image/jpeg;base64,AAA"}],
    )
    await nodes_module.generate_node(state)

    user_msg = captured["messages"][-1]
    assert user_msg["role"] == "user"
    parts = user_msg["content"]
    assert parts[0] == {"type": "text", "text": "who is this?"}
    # Caption block must not leak into the user turn — it is a retrieval
    # signal only, never user-facing prompt content.
    assert "[Image Analysis:" not in parts[0]["text"]


# ---------------------------------------------------------------------------
# Phase 25.1 — empty completion must be logged at WARNING so an operator
# can see why the guardrail blocked. The graph still propagates the empty
# string downstream; the abstain node + chat streamer handle the visible
# behaviour.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_logs_warning_when_groq_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def empty_chat(messages, *, model, **kwargs):
        return LLMResult(
            content="   ",
            model=model,
            prompt_tokens=42,
            completion_tokens=0,
            total_tokens=42,
            latency_ms=99,
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", empty_chat)

    with caplog.at_level(logging.WARNING, logger="rag.orchestrator.nodes"):
        result = await nodes_module.generate_node(_state())

    assert result["answer"] == ""
    assert result["abstained"] is False
    assert any(
        "generate.empty_completion" in rec.message
        for rec in caplog.records
    )


@pytest.mark.unit
async def test_generate_does_not_warn_when_content_present(
    captured: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="rag.orchestrator.nodes"):
        result = await nodes_module.generate_node(_state())

    assert result["answer"] == "Answer grounded in [1]."
    assert not any(
        "generate.empty_completion" in rec.message
        for rec in caplog.records
    )


@pytest.mark.unit
async def test_history_capped_at_last_n_turns(
    captured: dict[str, Any],
) -> None:
    """A very long history must not bloat the prompt; only the last 10
    turns are sent to the LLM."""

    long_hist = [
        {"role": "user", "content": f"turn {i}", "timestamp": float(i)}
        for i in range(50)
    ]
    state = _state(surface="spa", history=long_hist)
    await nodes_module.generate_node(state)

    history_in_prompt = captured["messages"][1:]
    assert len(history_in_prompt) == 10
    # Last entry must be the most recent.
    assert history_in_prompt[-1]["content"] == "turn 49"
