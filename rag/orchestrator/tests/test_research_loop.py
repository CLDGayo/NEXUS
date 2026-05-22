"""Phase 24 — orchestrator-level tests for the agentic iteration loop.

These exercise the full graph (router + planner + loop + accumulator)
through ``graph_module.run_graph`` with every external dependency
monkey-patched. The router and planner LLM calls are dispatched by
sniffing system-prompt substrings, mirroring the pattern already used in
``test_graph_smoke.py``.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from typing import Any

import pytest

from rag.config import settings
from rag.orchestrator import graph as graph_module
from rag.orchestrator.llm import LLMResult
from rag.retrieval.types import ScoredChunk


@pytest.fixture(autouse=True)
def _reset_graph() -> None:
    graph_module.reset_graph()
    yield
    graph_module.reset_graph()


def _stub_chunks(prefix: str, marker: str) -> list[ScoredChunk]:
    """Stub chunks tagged with both an arm prefix and a per-query marker.

    The marker lets loop tests assert that ``accumulated_context`` (and
    therefore the generate prompt) contains text from every sub-query
    pass, not just the last.
    """

    return [
        ScoredChunk(
            id=f"{prefix}-{marker}-{i}",
            text=(
                f"our plan starts at $99 per month including onboarding "
                f"[marker={marker}-{i}]"
            ),
            score=1.0 / i,
            metadata={"title": f"Note {prefix}-{marker}-{i}"},
        )
        for i in range(1, 4)
    ]


def _llm_result(
    text: str, *, prompt_tokens: int = 50, completion_tokens: int = 16
) -> LLMResult:
    return LLMResult(
        content=text,
        model="groq-llama-3.3-70b",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=20,
    )


async def _async_return(value: Any) -> Any:
    return value


def _is_router_prompt(text: str) -> bool:
    return "query router" in text or "EXACTLY one word" in text


def _is_planner_prompt(text: str) -> bool:
    return "decompose" in text.lower() and "json array" in text.lower()


def _is_rewriter_prompt(text: str) -> bool:
    return "standalone search query" in text


# ---------------------------------------------------------------------------
# Direct mode — router classifies "direct" → no planner call, single pass.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_direct_mode_skips_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever_call_count = {"dense": 0, "sparse": 0, "graph": 0}

    async def dense(q, *, k):
        retriever_call_count["dense"] += 1
        return _stub_chunks("d", "only")

    async def sparse(q, *, k):
        retriever_call_count["sparse"] += 1
        return _stub_chunks("s", "only")

    async def graph(q, *, k):
        retriever_call_count["graph"] += 1
        return _stub_chunks("g", "only")

    async def rerank(q, candidates, top_k=8):
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    plan_call_count = {"n": 0}

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if _is_router_prompt(system_text):
            return _llm_result(
                '{"is_research_mode": false, "intent": "mixed"}'
            )
        if _is_planner_prompt(system_text):
            plan_call_count["n"] += 1
            return _llm_result('["should not be called"]')
        return _llm_result(
            "Our plan starts at $99 per month [1] including onboarding [2]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="what is the price?",
        thread_key="direct_mode_t1",
        correlation_id="corr_direct",
        surface="messenger",
    )

    assert plan_call_count["n"] == 0, "planner LLM must not fire in direct mode"
    assert retriever_call_count == {"dense": 1, "sparse": 1, "graph": 1}
    assert result["is_research_mode"] is False
    # In direct mode the accumulator runs exactly once with the rerank output.
    assert result["accumulated_context"]
    assert len(result["accumulated_context"]) <= settings.retrieval_top_k


# ---------------------------------------------------------------------------
# Research mode — three sub-queries → three full fan-out passes.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_research_mode_runs_three_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever_queries: list[str] = []

    async def dense(q, *, k):
        retriever_queries.append(q)
        return _stub_chunks("d", q.replace(" ", "_"))

    async def sparse(q, *, k):
        return _stub_chunks("s", q.replace(" ", "_"))

    async def graph(q, *, k):
        return []

    async def rerank(q, candidates, top_k=8):
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if _is_router_prompt(system_text):
            return _llm_result(
                '{"is_research_mode": true, "intent": "mixed"}'
            )
        if _is_planner_prompt(system_text):
            return _llm_result('["alpha topic", "beta topic", "gamma topic"]')
        return _llm_result(
            "Across these areas [1] the plan is $99 [2] including onboarding [3]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="compare alpha, beta, and gamma initiatives",
        thread_key="research_mode_t1",
        correlation_id="corr_research",
        surface="messenger",
    )

    assert result["is_research_mode"] is True
    # Three sub-queries × one retrieve-dense call per iteration.
    assert retriever_queries == ["alpha topic", "beta topic", "gamma topic"]
    # accumulated_context aggregates chunks from all three passes.
    acc_ids = {chunk.id for chunk in result["accumulated_context"]}
    assert any("alpha_topic" in cid for cid in acc_ids)
    assert any("beta_topic" in cid for cid in acc_ids)
    assert any("gamma_topic" in cid for cid in acc_ids)


# ---------------------------------------------------------------------------
# Hard iteration cap — even if planner over-emits, loop terminates.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_research_loop_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lower ``research_max_iterations`` to 2 and verify the loop exits
    after exactly 2 sub-queries even though the planner emitted 3."""

    monkeypatch.setattr(settings, "research_max_iterations", 2)

    dense_calls: list[str] = []

    async def dense(q, *, k):
        dense_calls.append(q)
        return _stub_chunks("d", q.replace(" ", "_"))

    async def sparse(q, *, k):
        return []

    async def graph(q, *, k):
        return []

    async def rerank(q, candidates, top_k=8):
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if _is_router_prompt(system_text):
            return _llm_result(
                '{"is_research_mode": true, "intent": "mixed"}'
            )
        if _is_planner_prompt(system_text):
            # Planner emits 3, but cap is 2 so loop should run twice.
            return _llm_result('["q one", "q two", "q three"]')
        return _llm_result("Across [1] and [2] the plan is $99.")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="compare a, b, c",
        thread_key="research_cap_t1",
        correlation_id="corr_cap",
        surface="messenger",
    )

    assert result["research_iterations"] == 2
    assert dense_calls == ["q one", "q two"]


# ---------------------------------------------------------------------------
# Per-iteration top_k — research mode uses the smaller research_subquery_top_k.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_research_loop_per_iteration_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rerank_calls: list[int] = []

    async def dense(q, *, k):
        return _stub_chunks("d", q.replace(" ", "_"))

    async def sparse(q, *, k):
        return []

    async def graph(q, *, k):
        return []

    async def rerank(q, candidates, top_k=8):
        rerank_calls.append(top_k)
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if _is_router_prompt(system_text):
            return _llm_result(
                '{"is_research_mode": true, "intent": "mixed"}'
            )
        if _is_planner_prompt(system_text):
            return _llm_result('["a", "b", "c"]')
        return _llm_result("Across [1] [2] [3] the plan is $99.")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    await graph_module.run_graph(
        query="compare a, b, c",
        thread_key="research_topk_t1",
        correlation_id="corr_topk",
        surface="messenger",
    )

    assert rerank_calls, "rerank must fire at least once"
    assert all(k == settings.research_subquery_top_k for k in rerank_calls)


# ---------------------------------------------------------------------------
# Generate sees the merged accumulated_context, not just the last pass.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_research_generate_reads_accumulated_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def dense(q, *, k):
        return _stub_chunks("d", q.replace(" ", "_"))

    async def sparse(q, *, k):
        return []

    async def graph(q, *, k):
        return []

    async def rerank(q, candidates, top_k=8):
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    captured: dict[str, Any] = {}

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if _is_router_prompt(system_text):
            return _llm_result(
                '{"is_research_mode": true, "intent": "mixed"}'
            )
        if _is_planner_prompt(system_text):
            return _llm_result('["alpha topic", "beta topic", "gamma topic"]')
        # Generate call — capture the system prompt so we can inspect
        # the rendered context block.
        captured["system"] = system_text
        return _llm_result(
            "Across these areas [1] the plan is $99 [2] including onboarding [3]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    await graph_module.run_graph(
        query="compare alpha, beta, and gamma initiatives",
        thread_key="research_acc_t1",
        correlation_id="corr_acc",
        surface="messenger",
    )

    rendered = captured.get("system", "")
    assert "alpha_topic" in rendered
    assert "beta_topic" in rendered
    assert "gamma_topic" in rendered


# ---------------------------------------------------------------------------
# Rewrite + router order — router must see the rewritten search_query
# when a prior turn has set it, not the raw user query.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_router_classifies_against_rewritten_search_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def dense(q, *, k):
        return _stub_chunks("d", "only")

    async def sparse(q, *, k):
        return []

    async def graph(q, *, k):
        return []

    async def rerank(q, candidates, top_k=8):
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", rerank)

    router_user_msgs: list[str] = []

    async def fake_chat(messages, *, model, **kw):
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        user_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"),
            "",
        )
        if _is_rewriter_prompt(system_text):
            return _llm_result("compare alpha and beta initiatives")
        if _is_router_prompt(system_text):
            if isinstance(user_text, str):
                router_user_msgs.append(user_text)
            return _llm_result(
                '{"is_research_mode": false, "intent": "mixed"}'
            )
        return _llm_result("plan is $99 [1] with onboarding [2].")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    # Turn 1 — seed history so the rewriter fires on turn 2.
    await graph_module.run_graph(
        query="what about alpha and beta?",
        thread_key="router_rewrite_t1",
        correlation_id="corr_rrt1",
        surface="messenger",
    )
    router_user_msgs.clear()

    # Turn 2 — vague follow-up. Rewriter expands; router must see the
    # expanded form.
    await graph_module.run_graph(
        query="and?",
        thread_key="router_rewrite_t1",
        correlation_id="corr_rrt2",
        surface="messenger",
    )

    assert router_user_msgs, "router must have fired on turn 2"
    assert any("compare alpha and beta initiatives" in msg for msg in router_user_msgs)
