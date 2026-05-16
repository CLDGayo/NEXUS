"""LangGraph node implementations for the Nexus v2 cortex.

Each node is an async function returning a dict of partial state updates.
Nodes are imported by ``graph.py`` and registered with a ``StateGraph``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from rag.config import settings
from rag.guardrails.groundedness import (
    abstention_text,
    check_groundedness,
)
from rag.orchestrator.llm import LLMError, chat_complete
from rag.orchestrator.state import NexusState
from rag.retrieval.dense import dense_search
from rag.retrieval.rerank import rerank
from rag.retrieval.rrf import reciprocal_rank_fusion
from rag.retrieval.sparse import sparse_search
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


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

async def retrieve_dense_node(state: NexusState) -> dict:
    hits = await dense_search(state["query"], k=settings.retrieval_k_per_arm)
    return {"dense_hits": hits}


async def retrieve_sparse_node(state: NexusState) -> dict:
    hits = await sparse_search(state["query"], k=settings.retrieval_k_per_arm)
    return {"sparse_hits": hits}


async def fuse_node(state: NexusState) -> dict:
    dense = state.get("dense_hits", [])
    sparse = state.get("sparse_hits", [])
    fused = reciprocal_rank_fusion([dense, sparse])
    return {"fused": fused[: settings.retrieval_k_per_arm]}


async def rerank_node(state: NexusState) -> dict:
    candidates = state.get("fused", [])
    if not candidates:
        return {"reranked": []}
    reranked = await rerank(
        state["query"], candidates, top_k=settings.retrieval_top_k
    )
    return {"reranked": reranked}


# ---------------------------------------------------------------------------
# Generation + validation
# ---------------------------------------------------------------------------

async def generate_node(state: NexusState) -> dict:
    reranked = state.get("reranked", [])
    surface = state.get("surface", "messenger")
    prompt = _load_prompt(surface)
    rendered = prompt.replace("{context}", _format_context(reranked)).replace(
        "{question}", state["query"]
    )

    messages = [{"role": "system", "content": rendered}]

    try:
        answer = await chat_complete(
            messages,
            model=settings.generation_model,
            temperature=settings.generation_temperature,
            max_tokens=settings.generation_max_tokens,
        )
    except LLMError as exc:
        _log.warning("generation failed; abstaining: %s", exc)
        return {"answer": abstention_text(), "abstained": True}

    return {"answer": answer.strip(), "abstained": False}


async def guardrails_node(state: NexusState) -> dict:
    result = check_groundedness(
        state.get("answer", ""), state.get("reranked", [])
    )
    return {
        "guardrail_passed": result.passed,
        "guardrail_reason": result.reason,
        "citations": result.cited_ids,
    }


async def abstain_node(_: NexusState) -> dict:
    return {"answer": abstention_text(), "abstained": True}


# ---------------------------------------------------------------------------
# Conditional router
# ---------------------------------------------------------------------------

def guardrails_router(state: NexusState) -> Literal["respond", "abstain"]:
    if state.get("guardrail_passed"):
        return "respond"
    return "abstain"


async def respond_node(state: NexusState) -> dict:
    """Terminal pass-through; exists so the graph has a named exit per branch."""

    return {"answer": state.get("answer", "")}
