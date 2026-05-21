"""LangGraph node implementations for the Nexus v2 cortex.

Each node is an async function returning a dict of partial state updates.
Phase 5 wraps every node in ``@traced`` so each step emits an OTEL span
and the LLM generation emits a Langfuse ``generation`` event stitched to
the same trace.

The ``guardrails_node`` runs the Phase 5 ``GuardrailsPipeline`` (citation
+ exact-match + entropy), and routes blocked answers to the deterministic
fallback while flagging ``requires_human_handover=True``.

Phase 17 adds surface-aware vision intent overlays so image queries on
Messenger get customer-service-style responses while SPA queries get
structured knowledge-base retrieval.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from rag.config import settings
from rag.guardrails.handover import (
    HandoverSignal,
    emit_handover_signal,
    handover_fallback_text,
)
from rag.guardrails.pipeline import default_pipeline
from rag.orchestrator.llm import LLMError, LLMResult, chat_complete
from rag.orchestrator.state import NexusState
from rag.observability.decorators import traced
from rag.retrieval.dense import dense_search
from rag.retrieval.graph import graph_search
from rag.retrieval.rerank import rerank
from rag.retrieval.rrf import reciprocal_rank_fusion
from rag.retrieval.sparse import sparse_search
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_GUARDRAILS = default_pipeline()

# ---------------------------------------------------------------------------
# Phase 17 — vision intent overlays
# ---------------------------------------------------------------------------

_VISION_INTENT_MESSENGER = (
    "\n\n--- IMAGE QUERY INSTRUCTIONS ---\n"
    "The user has uploaded an image. Assume they are a customer inquiring "
    "about product availability, similarity, or identifying a person/service. "
    "Search the knowledge base for visual and semantic matches. Respond as a "
    "pleasant customer service representative. If a match is found, "
    "enthusiastically confirm it, provide the specific name/title (e.g., "
    "product name or person's name), and suggest related items or "
    "descriptions. Format cleanly for a chat interface."
)

_VISION_INTENT_SPA = (
    "\n\n--- IMAGE QUERY INSTRUCTIONS ---\n"
    "The user has uploaded an image to query their personal knowledge base. "
    "Search for visual and semantic matches. You must reply with a highly "
    "structured response. Include the following sections:\n"
    "**Source Document:** [Where this image/concept originated]\n"
    "**Identified Subject:** [Name of the person, product, or concept]\n"
    "**Context & Description:** [Details surrounding this item in the vault]\n"
    "**Related Topics:**\n"
    "- [Bullet points of adjacent concepts in the vault]"
)


def _load_prompt(surface: str) -> str:
    name = "system_brix.md" if surface == "messenger" else "system_internal.md"
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _format_context(chunks: list[ScoredChunk]) -> str:
    if not chunks:
        return "(no retrieved context)"
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        source = (
            chunk.metadata.get("title")
            or chunk.metadata.get("file")
            or chunk.id
        )
        body = chunk.text.strip().replace("\n\n", "\n")
        lines.append(f"[{index}] source: {source}\n{body}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Retrieval nodes
# ---------------------------------------------------------------------------

@traced("graph.node.retrieve_dense", kind="retrieval")
async def retrieve_dense_node(state: NexusState) -> dict:
    hits = await dense_search(state["query"], k=settings.retrieval_k_per_arm)
    return {"dense_hits": hits}


@traced("graph.node.retrieve_sparse", kind="retrieval")
async def retrieve_sparse_node(state: NexusState) -> dict:
    hits = await sparse_search(state["query"], k=settings.retrieval_k_per_arm)
    return {"sparse_hits": hits}


@traced("graph.node.retrieve_graph", kind="retrieval")
async def retrieve_graph_node(state: NexusState) -> dict:
    # The graph arm is more expensive on cold queries than dense/sparse
    # because it touches both SQLite and Qdrant. Still safe to fan out
    # in parallel — langgraph awaits all three at the fuse barrier.
    hits = await graph_search(state["query"], k=settings.retrieval_k_per_arm)
    return {"graph_hits": hits}


@traced("graph.node.fuse", kind="retrieval")
async def fuse_node(state: NexusState) -> dict:
    dense = state.get("dense_hits", [])
    sparse = state.get("sparse_hits", [])
    graph = state.get("graph_hits", [])
    # Three-arm reciprocal-rank fusion. Empty arms contribute nothing.
    fused = reciprocal_rank_fusion([dense, sparse, graph])
    return {"fused": fused[: settings.retrieval_k_per_arm]}


@traced("graph.node.rerank", kind="retrieval")
async def rerank_node(state: NexusState) -> dict:
    candidates = state.get("fused", [])
    if not candidates:
        return {"reranked": []}
    reranked = await rerank(
        state["query"], candidates, top_k=settings.retrieval_top_k
    )
    return {"reranked": reranked}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _collect_image_attachments(state: NexusState) -> list[dict]:
    """Return only valid image attachments, capped at ``vision_max_attachments``."""

    raw = state.get("attachments") or []
    images: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image":
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        images.append({"type": "image", "url": url})
    if len(images) > settings.vision_max_attachments:
        _log.info(
            "vision.attachments_truncated count=%d max=%d",
            len(images),
            settings.vision_max_attachments,
        )
        images = images[: settings.vision_max_attachments]
    return images


@traced("graph.node.generate", kind="llm")
async def generate_node(state: NexusState) -> dict:
    reranked = state.get("reranked", [])
    surface = state.get("surface", "messenger")
    prompt = _load_prompt(surface)
    context_block = _format_context(reranked)
    images = _collect_image_attachments(state)

    messages: list[dict[str, Any]]
    if images:
        # Multimodal path: instructions+context on system, question+images
        # on user turn. Keeps the citation rules visible while letting the
        # vision model see the actual image content.
        system_content = prompt.replace("{context}", context_block).replace(
            "{question}", "(see user message below)"
        )
        # Phase 17 — inject surface-specific vision intent overlay.
        if surface == "messenger":
            system_content += _VISION_INTENT_MESSENGER
        else:
            system_content += _VISION_INTENT_SPA
        user_parts: list[dict[str, Any]] = [
            {"type": "text", "text": state["query"]},
        ]
        for img in images:
            user_parts.append(
                {"type": "image_url", "image_url": {"url": img["url"]}}
            )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_parts},
        ]
        model = settings.vision_model
    else:
        # Text-only fallback unchanged from Phase 5 behaviour.
        rendered = prompt.replace("{context}", context_block).replace(
            "{question}", state["query"]
        )
        messages = [{"role": "system", "content": rendered}]
        model = settings.generation_model

    try:
        result: LLMResult = await chat_complete(
            messages,
            model=model,
            temperature=settings.generation_temperature,
            max_tokens=settings.generation_max_tokens,
        )
    except LLMError as exc:
        _log.warning(
            "generation failed; abstaining: %s (vision=%s)", exc, bool(images)
        )
        return {
            "answer": handover_fallback_text(),
            "abstained": True,
            "requires_human_handover": True,
            "handover_reason": f"llm error: {exc}",
        }

    return {
        "answer": result.content.strip(),
        "abstained": False,
        "llm_model": result.model,
        "llm_prompt_tokens": result.prompt_tokens,
        "llm_completion_tokens": result.completion_tokens,
        "llm_total_tokens": result.total_tokens,
        "llm_latency_ms": result.latency_ms,
    }


# ---------------------------------------------------------------------------
# Guardrails + routing
# ---------------------------------------------------------------------------

@traced("graph.node.guardrails", kind="guardrails")
async def guardrails_node(state: NexusState) -> dict:
    answer = state.get("answer", "")
    reranked = state.get("reranked", [])
    pipeline_result = _GUARDRAILS.validate(answer, retrieved=reranked)

    failed_names = pipeline_result.failed_names

    # Lift the CitationValidator's cited ids into state so downstream
    # surface adapters (Messenger sender, SPA stream) can render source
    # tags without re-parsing the answer.
    cited_ids: tuple[str, ...] = ()
    for r in pipeline_result.results:
        if r.name == "citation":
            cited_ids = tuple(r.metadata.get("cited_ids", []))
            break

    update: dict = {
        "guardrail_passed": not pipeline_result.blocked,
        "guardrail_reason": _format_pipeline_reason(pipeline_result),
        "uncertainty_score": pipeline_result.uncertainty_score,
        "validator_failures": failed_names,
        "citations": cited_ids,
        "requires_human_handover": pipeline_result.requires_handover
        or bool(state.get("requires_human_handover")),
    }

    if pipeline_result.blocked:
        update["handover_reason"] = update["guardrail_reason"]

        signal = HandoverSignal(
            correlation_id=state.get("correlation_id", ""),
            thread_key=state.get("thread_key", ""),
            surface=state.get("surface", "unknown"),
            reason=update["guardrail_reason"] or "guardrail block",
            validators_failed=failed_names,
            uncertainty_score=pipeline_result.uncertainty_score,
            retrieved_count=len(reranked),
            answer_blocked=True,
        )
        emit_handover_signal(signal)

    return update


def _format_pipeline_reason(pipeline_result) -> str | None:
    failures = pipeline_result.critical_failures
    if not failures:
        return None
    parts = [f"{r.name}: {r.reason or 'failed'}" for r in failures]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Terminal nodes
# ---------------------------------------------------------------------------

@traced("graph.node.respond", kind="terminal")
async def respond_node(state: NexusState) -> dict:
    return {"answer": state.get("answer", "")}


@traced("graph.node.abstain", kind="terminal")
async def abstain_node(state: NexusState) -> dict:
    return {
        "answer": handover_fallback_text(),
        "abstained": True,
        "requires_human_handover": True,
        "handover_reason": state.get("handover_reason")
        or state.get("guardrail_reason")
        or "guardrail abstain",
    }


# ---------------------------------------------------------------------------
# Conditional router
# ---------------------------------------------------------------------------

def guardrails_router(state: NexusState) -> Literal["respond", "abstain"]:
    if state.get("guardrail_passed"):
        return "respond"
    return "abstain"
