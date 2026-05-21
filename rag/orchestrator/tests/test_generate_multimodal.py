"""Phase 15 — `generate_node` multimodal routing tests.

Each test stubs `chat_complete` to capture the messages + model the node
sends to LiteLLM, then asserts the multimodal-vs-text branching is correct.
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
