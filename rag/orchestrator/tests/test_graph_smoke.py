"""Smoke test that exercises the full LangGraph state graph end-to-end with
mocked retrieval + reranker + LLM. Asserts node sequencing, RRF + rerank
output flow, guardrails branching, handover signaling, and token capture."""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

import pytest

from rag.orchestrator import graph as graph_module
from rag.orchestrator.llm import LLMError, LLMResult
from rag.retrieval.types import ScoredChunk


@pytest.fixture(autouse=True)
def _reset_graph() -> None:
    graph_module.reset_graph()
    yield
    graph_module.reset_graph()


def _stub_chunks(prefix: str) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            id=f"{prefix}-{i}",
            text=f"our plan starts at $99 per month [prefix={prefix}-{i}] including onboarding",
            score=1.0 / i,
            metadata={"title": f"Note {prefix}-{i}"},
        )
        for i in range(1, 4)
    ]


def _llm_result(text: str, *, prompt_tokens: int = 120, completion_tokens: int = 24) -> LLMResult:
    return LLMResult(
        content=text,
        model="groq-llama-3.3-70b",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=42,
    )


@pytest.mark.unit
async def test_graph_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *args, **kwargs: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *args, **kwargs: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *args, **kwargs: _async_return(_stub_chunks("g")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.rerank",
        lambda query, candidates, top_k=8: _async_return(candidates[:top_k]),
    )

    async def fake_chat(*_args, **_kwargs):
        # Grounded answer — $99 + onboarding both appear in stub chunks above.
        return _llm_result("Our plan starts at $99 per month [1] and includes onboarding [2].")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test",
        correlation_id="corr_test",
        surface="messenger",
    )

    assert "[1]" in result["answer"]
    assert result["guardrail_passed"] is True
    assert result["abstained"] is False
    assert result.get("requires_human_handover") in (False, None)
    assert len(result["citations"]) >= 1
    assert result["reranked"], "rerank must emit chunks for valid retrieval"

    # Phase 5 — usage capture
    assert result["llm_model"] == "groq-llama-3.3-70b"
    assert result["llm_prompt_tokens"] == 120
    assert result["llm_completion_tokens"] == 24
    assert result["llm_total_tokens"] == 144
    assert "uncertainty_score" in result


@pytest.mark.unit
async def test_graph_abstains_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *a, **kw: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *a, **kw: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *a, **kw: _async_return([]),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.rerank",
        lambda q, c, top_k=8: _async_return(c[:top_k]),
    )

    async def boom(*_a, **_kw):
        raise LLMError("upstream proxy 502")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", boom)

    result = await graph_module.run_graph(
        query="anything",
        thread_key="psid_test_2",
        correlation_id="corr_2",
        surface="messenger",
    )

    assert result["abstained"] is True
    assert result["requires_human_handover"] is True
    assert result.get("handover_reason")
    assert "human" in result["answer"].lower() or "route" in result["answer"].lower()


@pytest.mark.unit
async def test_graph_abstains_on_fabricated_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *a, **kw: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *a, **kw: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *a, **kw: _async_return([]),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.rerank",
        lambda q, c, top_k=8: _async_return(c[:top_k]),
    )

    # LLM emits a price NOT in the retrieved context → exact_match must block.
    async def fabricated(*_a, **_kw):
        return _llm_result("Our pricing is exactly $147.99 per month [1].")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fabricated)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test_3",
        correlation_id="corr_3",
        surface="messenger",
    )

    assert result["guardrail_passed"] is False
    assert result["abstained"] is True
    assert result["requires_human_handover"] is True
    assert "exact_match" in result["validator_failures"]


@pytest.mark.unit
async def test_graph_abstains_on_uncited_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *a, **kw: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *a, **kw: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *a, **kw: _async_return([]),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.rerank",
        lambda q, c, top_k=8: _async_return(c[:top_k]),
    )

    async def uncited(*_a, **_kw):
        return _llm_result("Our plan starts at $99 per month.")  # no [n] citation

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", uncited)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test_4",
        correlation_id="corr_4",
        surface="messenger",
    )

    assert result["guardrail_passed"] is False
    assert result["abstained"] is True
    assert "citation" in result["validator_failures"]


# ---------------------------------------------------------------------------
# Phase 7 — 3-arm RRF fusion regression
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_graph_three_arm_fusion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct stubs for each arm. The fused list visible to rerank must
    contain ids from all three arms."""

    captured_for_rerank: list[list[ScoredChunk]] = []

    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *a, **kw: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *a, **kw: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *a, **kw: _async_return(_stub_chunks("g")),
    )

    async def capture_rerank(query, candidates, top_k=8):
        captured_for_rerank.append(list(candidates))
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.rerank", capture_rerank)
    monkeypatch.setattr(
        "rag.orchestrator.nodes.chat_complete",
        lambda *a, **kw: _async_return(
            _llm_result("Our plan starts at $99 per month [1] including onboarding [2].")
        ),
    )

    await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_3arm",
        correlation_id="corr_3arm",
        surface="messenger",
    )

    assert captured_for_rerank, "rerank should be called"
    fused_ids = {c.id for c in captured_for_rerank[0]}
    # IDs in _stub_chunks are `{prefix}-{i}`; each arm uses a distinct
    # prefix so we can prove the graph arm contributed.
    assert any(cid.startswith("d-") for cid in fused_ids)
    assert any(cid.startswith("s-") for cid in fused_ids)
    assert any(cid.startswith("g-") for cid in fused_ids)


# ---------------------------------------------------------------------------
# Phase 15 — multimodal attachments propagate to generate
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_graph_threads_attachments_to_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rag.orchestrator.nodes.dense_search",
        lambda *a, **kw: _async_return(_stub_chunks("d")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.sparse_search",
        lambda *a, **kw: _async_return(_stub_chunks("s")),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.graph_search",
        lambda *a, **kw: _async_return([]),
    )
    monkeypatch.setattr(
        "rag.orchestrator.nodes.rerank",
        lambda q, c, top_k=8: _async_return(c[:top_k]),
    )

    captured: dict = {}

    async def fake_chat(messages, *, model, **kw):
        captured["messages"] = messages
        captured["model"] = model
        return _llm_result(
            "Our plan starts at $99 per month [1] including onboarding [2]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_mm",
        correlation_id="corr_mm",
        surface="messenger",
        attachments=[{"type": "image", "url": "data:image/png;base64,AA"}],
    )

    from rag.config import settings as _settings

    assert captured["model"] == _settings.vision_model
    assert len(captured["messages"]) == 2
    user_msg = captured["messages"][1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert any(p.get("type") == "image_url" for p in user_msg["content"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_return(value):
    return value
