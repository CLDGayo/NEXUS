"""LangGraph state schema for the Nexus v2 cortex.

A single TypedDict shared by every node. Optional fields are populated as
the graph traverses; only ``query``, ``thread_key``, ``correlation_id``,
and ``surface`` are required at entry.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal, TypedDict

from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)

Surface = Literal["messenger", "spa", "test"]

# Phase 21 — history is JSON-serialized to the Postgres checkpointer on
# every state write. Keep it tight so a multi-month thread doesn't bloat
# its checkpoint row past JSONB's practical ceiling, and keep it strictly
# text so a future PR can't silently leak a multimodal content block
# (e.g. a base64 data: URI) into the persisted state.
HISTORY_MAX_ENTRIES = 40
HISTORY_MAX_CHARS = 64 * 1024


def _is_text_entry(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    content = item.get("content")
    role = item.get("role")
    return isinstance(content, str) and isinstance(role, str)


def _trim(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop oldest entries until the list fits both caps."""

    if len(entries) > HISTORY_MAX_ENTRIES:
        entries = entries[-HISTORY_MAX_ENTRIES:]
    total = sum(len(e.get("content", "")) for e in entries)
    while entries and total > HISTORY_MAX_CHARS:
        dropped = entries.pop(0)
        total -= len(dropped.get("content", ""))
    return entries


def append_history(
    left: list[dict[str, str]] | None, right: list[dict[str, str]] | None
) -> list[dict[str, str]]:
    """Reducer for ``NexusState.history``.

    Strictly enforces ``{"role": str, "content": str}`` shape so a future
    PR that tries to append a multimodal LangChain content block (list
    of dicts with image_url parts) cannot pollute the persisted state.
    Violations are dropped with a structured ``state.history.dropped_nontext``
    log line — the user-visible answer is unaffected.
    """

    if left is None:
        left = []
    if right is None:
        right = []

    accepted: list[dict[str, str]] = []
    dropped = 0
    for item in right:
        if _is_text_entry(item):
            accepted.append({"role": str(item["role"]), "content": str(item["content"])})
        else:
            dropped += 1
    if dropped:
        _log.warning("state.history.dropped_nontext count=%d", dropped)

    merged = list(left) + accepted
    return _trim(merged)


class NexusState(TypedDict, total=False):
    # Entry fields (set by the webhook adapter)
    query: str
    thread_key: str
    correlation_id: str
    surface: Surface
    # Phase 15 — multimodal attachments forwarded from the surface adapter.
    # Each item: {"type": "image", "url": "data:image/jpeg;base64,..."} (SPA)
    # or {"type": "image", "url": "https://scontent.../..."} (Messenger CDN).
    attachments: list[dict]

    # Retrieval pipeline outputs
    dense_hits: list[ScoredChunk]
    sparse_hits: list[ScoredChunk]
    # Phase 7 — third parallel arm: wikilink graph expansion.
    graph_hits: list[ScoredChunk]
    fused: list[ScoredChunk]
    reranked: list[ScoredChunk]

    # Generation + validation
    answer: str
    citations: tuple[str, ...]
    guardrail_passed: bool
    guardrail_reason: str | None

    # Bookkeeping
    abstained: bool

    # Phase 5 — guardrails + observability
    requires_human_handover: bool
    handover_reason: str | None
    uncertainty_score: float
    validator_failures: tuple[str, ...]

    # Phase 5 — LLM usage capture
    llm_model: str
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_latency_ms: int

    # Phase 18 — conversational memory
    history: Annotated[list[dict[str, str]], append_history]
