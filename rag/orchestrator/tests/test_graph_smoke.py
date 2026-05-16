"""Smoke test that exercises the full LangGraph state graph end-to-end with
mocked retrieval + reranker + LLM. Asserts node sequencing, RRF + rerank
output flow, guardrails branching, and citation parsing."""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

import pytest

from rag.orchestrator import graph as graph_module
from rag.orchestrator.llm import LLMError
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
            text=f"text body {prefix}-{i}",
            score=1.0 / i,
            metadata={"title": f"Note {prefix}-{i}"},
        )
        for i in range(1, 4)
    ]


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
        "rag.orchestrator.nodes.rerank",
        lambda query, candidates, top_k=8: _async_return(candidates[:top_k]),
    )

    async def fake_chat(*_args, **_kwargs):
        return "Our plan starts at $99 [1] and includes onboarding [2]."

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test",
        correlation_id="corr_test",
        surface="messenger",
    )

    assert "[1]" in result["answer"]
    assert result["guardrail_passed"] is True
    assert len(result["citations"]) == 2
    assert result["reranked"], "rerank must emit chunks for valid retrieval"
    assert "abstained" in result and result["abstained"] is False


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
    assert "human" in result["answer"].lower() or "route" in result["answer"].lower()


@pytest.mark.unit
async def test_graph_abstains_on_ungrounded_answer(
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
        "rag.orchestrator.nodes.rerank",
        lambda q, c, top_k=8: _async_return(c[:top_k]),
    )

    # LLM emits a factual claim with no citations → groundedness should fail.
    async def ungrounded(*_a, **_kw):
        return "Our pricing starts at exactly $147.99 per month."

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", ungrounded)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test_3",
        correlation_id="corr_3",
        surface="messenger",
    )

    assert result["guardrail_passed"] is False
    assert result["abstained"] is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_return(value):
    return value
