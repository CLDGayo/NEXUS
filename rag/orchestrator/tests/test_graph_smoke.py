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


def _llm_result(
    text: str, *, prompt_tokens: int = 120, completion_tokens: int = 24
) -> LLMResult:
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
        return _llm_result(
            "Our plan starts at $99 per month [1] and includes onboarding [2]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    result = await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_test",
        correlation_id="corr_test",
        surface="messenger",
        tenant_id="hunter",
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
        tenant_id="hunter",
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

    # LLM emits prices NOT in the retrieved context → exact_match must block.
    # Phase 19.1 raised the default `max_suspicious` from 0 → 2 and added a
    # short-turn bypass; we now need 3+ fabrications and a multi-word query
    # to still trigger the block, which is the contract this test pins.
    # Phase 33.1 bumped the Messenger surface to ``max_suspicious=5`` for the
    # SDR persona, so this test now exercises the SPA surface (still strict
    # at 2) to keep the regression coverage honest. The "fabrication blocks"
    # contract is what matters; surface choice is incidental.
    async def fabricated(*_a, **_kw):
        return _llm_result(
            "Pricing is exactly $147.99 per month [1], jumping to $258.50 "
            "in year two [1], and $911.42 in year three [1] under the "
            "standard contractual escalator clause noted above."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fabricated)

    result = await graph_module.run_graph(
        # Query >8 tokens so the short-turn bypass doesn't skip the
        # validator the test is actually exercising (Phase 19.1 bypass).
        query="tell me about the full pricing schedule across all of our annual tiers",
        thread_key="psid_test_3",
        correlation_id="corr_3",
        surface="spa",
        tenant_id="hunter",
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
        # Query >8 tokens to exit the short-turn bypass and exercise the
        # strict citation path this test is documenting.
        query="please give me a detailed breakdown of our monthly pricing",
        thread_key="psid_test_4",
        correlation_id="corr_4",
        surface="messenger",
        tenant_id="hunter",
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
            _llm_result(
                "Our plan starts at $99 per month [1] including onboarding [2]."
            )
        ),
    )

    await graph_module.run_graph(
        query="pricing?",
        thread_key="psid_3arm",
        correlation_id="corr_3arm",
        surface="messenger",
        tenant_id="hunter",
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
        tenant_id="hunter",
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


# ---------------------------------------------------------------------------
# Phase 22.1 — Rewrite must run BEFORE vision so the 8B coreference resolver
# only sees raw conversational text, never the dense [Image Analysis: ...]
# block emitted by preprocess_vision_node.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_graph_orders_rewrite_before_vision_on_multimodal_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag.config import settings as _settings

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

    calls: list[dict] = []

    async def fake_chat(messages, *, model, **kw):
        calls.append({"messages": messages, "model": model})
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        if "standalone search query" in system_text:
            return _llm_result("standalone rewritten query about clarence")
        if "Briefly describe this image" in system_text:
            return _llm_result("photo of a person in front of a window")
        return _llm_result(
            "Acknowledged, clarence — your plan starts at $99 per month [1]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    # Turn 1 — seed history so the rewrite branch fires on turn 2.
    await graph_module.run_graph(
        query="what's the pricing?",
        thread_key="thread_phase22_1",
        correlation_id="corr_22_1_t1",
        surface="messenger",
        tenant_id="hunter",
    )
    turn1_call_count = len(calls)
    assert turn1_call_count >= 1, "turn 1 must hit at least the generate model"

    # Turn 2 — multimodal follow-up. Rewrite must fire BEFORE vision caption.
    await graph_module.run_graph(
        query="hi i'm clarence and this is my photo",
        thread_key="thread_phase22_1",
        correlation_id="corr_22_1_t2",
        surface="messenger",
        tenant_id="hunter",
        attachments=[{"type": "image", "url": "https://example.test/img.png"}],
    )

    # Phase 24 — turn 2 LLM call ordering is now:
    #   rewrite (followup) → vision_caption (vision) → route_query (followup)
    #   → generate (vision because images attached)
    turn2 = calls[turn1_call_count:]
    assert len(turn2) >= 4, (
        f"expected >=4 LLM calls on turn 2 (rewrite + vision + router + "
        f"generate), got {len(turn2)}: {[c['model'] for c in turn2]}"
    )

    def _system(call):
        return next(
            (m.get("content", "") for m in call["messages"] if m["role"] == "system"),
            "",
        )

    rewrite_call = next(c for c in turn2 if "standalone search query" in _system(c))
    vision_call = next(c for c in turn2 if "Briefly describe this image" in _system(c))
    router_call = next(c for c in turn2 if "query router" in _system(c))
    generate_call = turn2[-1]

    # 1. Rewrite must be first and must use the 8B followup model.
    assert turn2[0] is rewrite_call, (
        f"first LLM call on turn 2 should be the rewrite, got {turn2[0]['model']!r}"
    )
    assert rewrite_call["model"] == _settings.followup_model

    # 2. Rewrite must see ONLY clean conversational text — never the caption.
    rewrite_user_msg = next(m for m in rewrite_call["messages"] if m["role"] == "user")
    rewrite_user_content = rewrite_user_msg["content"]
    assert isinstance(rewrite_user_content, str)
    assert "hi i'm clarence and this is my photo" in rewrite_user_content
    assert "[Image Analysis:" not in rewrite_user_content, (
        "Phase 22.1 invariant violated: rewrite node received caption block"
    )

    # 3. Vision caption call must come AFTER rewrite and use vision_model.
    assert vision_call["model"] == _settings.vision_model
    vision_user_msg = next(m for m in vision_call["messages"] if m["role"] == "user")
    assert isinstance(vision_user_msg["content"], list)
    assert any(p.get("type") == "image_url" for p in vision_user_msg["content"])

    # 4. Phase 24 router runs after vision and uses the fast followup model.
    assert router_call["model"] == _settings.followup_model

    # 5. Generate call comes last; with image attached it routes to vision_model.
    assert generate_call["model"] == _settings.vision_model


# ---------------------------------------------------------------------------
# Phase 18 — Conversational history and query contextualization
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_graph_query_contextualization_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Setup mock functions for search and rerank
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

    chat_calls = []

    async def fake_chat(messages, *, model, **kw):
        chat_calls.append((messages, model))
        # Check if this is the query contextualization call (system prompt has 'standalone')
        is_contextualize = any(
            "standalone" in m.get("content", "")
            for m in messages
            if m.get("role") == "system"
        )
        if is_contextualize:
            return _llm_result("pricing and plans details")
        return _llm_result(
            "Our plan starts at $99 per month [1] including onboarding [2]."
        )

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    # First turn: Ask "pricing?"
    result1 = await graph_module.run_graph(
        query="pricing?",
        thread_key="thread_context_test",
        correlation_id="corr_c1",
        surface="messenger",
        tenant_id="hunter",
    )

    assert result1["guardrail_passed"] is True
    # Verify the history is now populated. Phase 22 stamps each entry with
    # a numeric timestamp; assert role+content shape independently so the
    # test does not depend on the exact float value.
    assert "history" in result1
    assert len(result1["history"]) == 2
    h0, h1 = result1["history"]
    assert h0["role"] == "user"
    assert h0["content"] == "pricing?"
    assert isinstance(h0["timestamp"], float)
    assert h1["role"] == "assistant"
    assert (
        h1["content"]
        == "Our plan starts at $99 per month [1] including onboarding [2]."
    )
    assert isinstance(h1["timestamp"], float)

    # Second turn: Ask a follow-up "yes please"
    result2 = await graph_module.run_graph(
        query="yes please",
        thread_key="thread_context_test",
        correlation_id="corr_c2",
        surface="messenger",
        tenant_id="hunter",
    )

    # Verify that query contextualization was called and LLM reformulated the query
    assert len(chat_calls) >= 3  # 1 for turn 1, 2 for turn 2 (contextualize + generate)
    # Check that one of the chat completions was the contextualization one
    contextualize_call = None
    for msgs, model in chat_calls:
        if any(
            "standalone" in m.get("content", "")
            for m in msgs
            if m.get("role") == "system"
        ):
            contextualize_call = msgs
            break
    assert contextualize_call is not None
    # Check that history was passed in the user content
    user_msg = next(m for m in contextualize_call if m["role"] == "user")
    assert "pricing?" in user_msg["content"]
    assert "yes please" in user_msg["content"]


# ---------------------------------------------------------------------------
# Phase 22.2 — query / search_query separation (Robotic Repetition fix)
#
# The rewriter must populate ``search_query`` for the retrieval arms, and
# the generation LLM must still see the user's original ``query`` so it
# replies in natural conversational register instead of echoing the
# rewritten search string back as third-person prose.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_graph_separates_search_query_from_user_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag.config import settings as _settings

    retriever_queries: list[str] = []
    rerank_queries: list[str] = []

    async def capture_dense(q, *, k, **_kwargs):
        retriever_queries.append(q)
        return _stub_chunks("d")

    async def capture_sparse(q, *, k, **_kwargs):
        retriever_queries.append(q)
        return _stub_chunks("s")

    async def capture_graph(q, *, k, **_kwargs):
        retriever_queries.append(q)
        return []

    async def capture_rerank(q, candidates, top_k=8):
        rerank_queries.append(q)
        return candidates[:top_k]

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", capture_dense)
    monkeypatch.setattr("rag.orchestrator.nodes.sparse_search", capture_sparse)
    monkeypatch.setattr("rag.orchestrator.nodes.graph_search", capture_graph)
    monkeypatch.setattr("rag.orchestrator.nodes.rerank", capture_rerank)

    chat_calls: list[dict] = []

    async def fake_chat(messages, *, model, **kw):
        chat_calls.append({"messages": messages, "model": model})
        system_text = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"),
            "",
        )
        # Rewrite call — return a deliberately different, robotic search
        # string so we can prove generation did NOT inherit it.
        if "standalone search query" in system_text:
            return _llm_result("Clarence Gayo projects list")
        return _llm_result("His projects include Atlas [1] and the Q3 redesign [2].")

    monkeypatch.setattr("rag.orchestrator.nodes.chat_complete", fake_chat)

    # Turn 1 — seed history so the rewriter fires on turn 2.
    await graph_module.run_graph(
        query="tell me about Clarence Gayo",
        thread_key="thread_phase22_2",
        correlation_id="corr_22_2_t1",
        surface="messenger",
        tenant_id="hunter",
    )
    turn1_calls = len(chat_calls)
    retriever_queries.clear()
    rerank_queries.clear()

    # Turn 2 — natural follow-up using a pronoun. Rewriter expands to the
    # robotic "Clarence Gayo projects list" form; the user must still see
    # a natural answer because generate_node reads the original query.
    await graph_module.run_graph(
        query="what are his projects?",
        thread_key="thread_phase22_2",
        correlation_id="corr_22_2_t2",
        surface="messenger",
        tenant_id="hunter",
    )

    turn2 = chat_calls[turn1_calls:]
    assert len(turn2) >= 2, (
        f"expected rewrite + generate calls on turn 2, got {len(turn2)}"
    )

    # 1. Rewrite call uses the fast followup model.
    rewrite_call = turn2[0]
    assert rewrite_call["model"] == _settings.followup_model

    # 2. Retrievers received the rewritten search string, not the raw query.
    assert retriever_queries, "retrieval arms must have been called on turn 2"
    for q in retriever_queries:
        assert q == "Clarence Gayo projects list", (
            f"retrieval saw {q!r}; expected the rewritten search_query"
        )
    # And the reranker uses the same string.
    assert rerank_queries == ["Clarence Gayo projects list"]

    # 3. Generation system prompt carries the USER'S original phrasing,
    # NOT the rewritten search string. This is the Robotic-Repetition fix.
    generate_call = turn2[-1]
    system_text = next(
        m.get("content", "")
        for m in generate_call["messages"]
        if m.get("role") == "system"
    )
    assert "what are his projects?" in system_text
    assert "Clarence Gayo projects list" not in system_text


@pytest.mark.unit
async def test_graph_first_turn_retrieves_with_original_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the first turn there is no history → rewriter is a no-op →
    ``search_query`` stays unset → retrievers must fall back to ``query``."""

    retriever_queries: list[str] = []

    async def capture_dense(q, *, k, **_kwargs):
        retriever_queries.append(q)
        return _stub_chunks("d")

    monkeypatch.setattr("rag.orchestrator.nodes.dense_search", capture_dense)
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
    monkeypatch.setattr(
        "rag.orchestrator.nodes.chat_complete",
        lambda *a, **kw: _async_return(
            _llm_result(
                "Our plan starts at $99 per month [1] including onboarding [2]."
            )
        ),
    )

    await graph_module.run_graph(
        query="pricing?",
        thread_key="thread_phase22_2_first",
        correlation_id="corr_22_2_first",
        surface="messenger",
        tenant_id="hunter",
    )

    assert retriever_queries == ["pricing?"]
