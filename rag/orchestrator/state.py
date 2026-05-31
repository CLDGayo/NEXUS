"""LangGraph state schema for the Nexus v2 cortex.

A single TypedDict shared by every node. Optional fields are populated as
the graph traverses; only ``query``, ``thread_key``, ``correlation_id``,
and ``surface`` are required at entry.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal, TypedDict

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
# Phase 22 — rolling 7-day TTL. Entries older than this are dropped on
# every reducer pass, so a long-running thread organically sheds context
# weekly instead of growing forever.
HISTORY_TTL_SECONDS = 7 * 24 * 60 * 60


def _is_text_entry(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    content = item.get("content")
    role = item.get("role")
    if not (isinstance(content, str) and isinstance(role, str)):
        return False
    ts = item.get("timestamp")
    if ts is not None and not isinstance(ts, (int, float)):
        return False
    return True


def _trim(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop oldest entries until the list fits both caps."""

    if len(entries) > HISTORY_MAX_ENTRIES:
        entries = entries[-HISTORY_MAX_ENTRIES:]
    total = sum(len(str(e.get("content", ""))) for e in entries)
    while entries and total > HISTORY_MAX_CHARS:
        dropped = entries.pop(0)
        total -= len(str(dropped.get("content", "")))
    return entries


def append_history(
    left: list[dict[str, object]] | None,
    right: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    """Reducer for ``NexusState.history``.

    Strictly enforces ``{"role": str, "content": str, "timestamp": float?}``
    shape so a future PR that tries to append a multimodal LangChain content
    block (list of dicts with image_url parts) cannot pollute the persisted
    state. Violations are dropped with a structured
    ``state.history.dropped_nontext`` log line — the user-visible answer is
    unaffected.

    Phase 22 — applies a rolling 7-day TTL on every reduction. Entries with
    a ``timestamp`` older than ``HISTORY_TTL_SECONDS`` are evicted. Legacy
    entries written before Phase 22 (no ``timestamp`` key) are stamped with
    ``now`` on first read so they get one full TTL window of grace before
    expiring — no abrupt context loss on deploy.
    """

    if left is None:
        left = []
    if right is None:
        right = []

    now = time.time()
    cutoff = now - HISTORY_TTL_SECONDS

    accepted: list[dict[str, object]] = []
    dropped = 0
    for item in right:
        if not _is_text_entry(item):
            dropped += 1
            continue
        entry: dict[str, object] = {
            "role": str(item["role"]),
            "content": str(item["content"]),
        }
        raw_ts = item.get("timestamp") if isinstance(item, dict) else None
        entry["timestamp"] = float(raw_ts) if isinstance(raw_ts, (int, float)) else now
        accepted.append(entry)
    if dropped:
        _log.warning("state.history.dropped_nontext count=%d", dropped)

    merged = list(left) + accepted

    fresh: list[dict[str, object]] = []
    for entry in merged:
        if not isinstance(entry, dict):
            continue
        ts = entry.get("timestamp")
        if not isinstance(ts, (int, float)):
            entry = {**entry, "timestamp": now}
            ts = now
        if float(ts) >= cutoff:
            fresh.append(entry)

    return _trim(fresh)


# Phase 24 — agentic iteration loop accumulator. Caps far above the
# practical budget (3 iters × 4 chunks = 12) so a planner mis-emit that
# slipped past the iteration cap still can't bloat the generation prompt
# unboundedly.
ACCUMULATED_CHUNKS_CAP = 24


def append_chunks(
    left: list[ScoredChunk] | None,
    right: list[ScoredChunk] | None,
) -> list[ScoredChunk]:
    """Reducer for ``NexusState.accumulated_context``.

    Appends ``right`` onto ``left``, deduplicates by ``ScoredChunk.id``
    keeping the first occurrence (so the highest-confidence pass wins),
    and trims to ``ACCUMULATED_CHUNKS_CAP`` from the tail so the most
    recent sub-query passes can't be evicted by older ones.
    """

    merged = list(left or []) + list(right or [])
    seen: set[str] = set()
    deduped: list[ScoredChunk] = []
    for chunk in merged:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        deduped.append(chunk)
    if len(deduped) > ACCUMULATED_CHUNKS_CAP:
        deduped = deduped[-ACCUMULATED_CHUNKS_CAP:]
    return deduped


class NexusState(TypedDict, total=False):
    # Entry fields (set by the webhook adapter)
    query: str
    thread_key: str
    correlation_id: str
    surface: Surface
    # Phase 29 — strict tenancy. Carries the active tenant SLUG (not UUID).
    # Populated at graph entry by the surface adapter and never mutated
    # mid-run. Every retrieval node consumes it to build the Qdrant filter.
    tenant_id: str
    # Phase 15 — multimodal attachments forwarded from the surface adapter.
    # Each item: {"type": "image", "url": "data:image/jpeg;base64,..."} (SPA)
    # or {"type": "image", "url": "https://scontent.../..."} (Messenger CDN).
    attachments: list[dict]

    # Phase 22.2 — rewritten / caption-augmented query consumed by the
    # retrieval+rerank arms only. The original ``query`` stays immutable
    # so ``generate_node`` and the history reducer keep the user's natural
    # phrasing. Unset on first turn (no rewrite, no vision caption) —
    # retrievers fall back to ``query`` via ``_retrieval_query``.
    search_query: str

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

    # Phase 18 — conversational memory. Phase 22 adds an optional
    # ``timestamp`` (epoch seconds) on every entry; the reducer enforces a
    # rolling 7-day TTL.
    history: Annotated[list[dict[str, object]], append_history]

    # Phase 24 — agentic iterative plan-and-solve loop.
    # ``is_research_mode`` set by ``route_query_node``; when true the
    # graph takes the plan→decompose→loop path. ``sub_queries`` is the
    # FIFO queue ``next_subquery_node`` pops from on each iteration.
    # ``accumulated_context`` collects reranked chunks across iterations
    # via the ``append_chunks`` reducer. ``research_iterations`` is the
    # hard-cap counter that ``loop_decision`` checks against
    # ``settings.research_max_iterations``.
    is_research_mode: bool
    sub_queries: list[str]
    accumulated_context: Annotated[list[ScoredChunk], append_chunks]
    research_iterations: int

    # Phase 25 — query intent classification feeds dynamic RRF weights in
    # ``fuse_node``. Set by ``route_query_node`` alongside
    # ``is_research_mode``. ``None`` means the router didn't run or its
    # response was unparseable — ``fuse_node`` falls back to uniform
    # (1.0) per-arm weights, preserving the pre-Phase-25 behavior.
    query_intent: Literal["factual", "conceptual", "mixed"] | None

    # Phase 32 — Messenger product carousel. Populated by
    # ``enrich_with_products_node`` (messenger surface only) with a
    # serialised ``ProductCarouselBlock``. ``build_outbound_payload``
    # reads this key and attaches the carousel to the ReplyBlock; absent
    # on every surface but messenger.
    product_carousel: dict[str, Any]

    # Phase 35 — Cognitive Empathy. Populated by ``sentiment_analysis_node``
    # with one of {"frustrated", "urgent", "excited", "neutral"} or None
    # (node didn't run / parse failure). ``generate_node`` reads this to
    # apply behavioral overlays and optionally suppress the SDR persona.
    sentiment: str | None

    # Phase 36 — Deep Commerce Context. ``sender_id`` is the raw Messenger
    # PSID (or SPA user id) forwarded by the surface adapter; the enrichment
    # node uses it as the lookup key against GoHighLevel via n8n. Identical
    # in value to ``thread_key`` on the Messenger surface today, but kept
    # as a discrete field so a future SPA surface can decouple session
    # threading from the CRM identity.
    sender_id: str

    # Phase 36 — Deep Commerce Context. Populated by
    # ``enrich_customer_profile_node`` with whatever JSON the n8n →
    # GoHighLevel webhook returns (name, lifetime_spend, last_order_date,
    # tags, segment, etc.). ``None`` means the lookup didn't run (webhook
    # not configured) or failed; ``generate_node`` then skips the CRM
    # block silently so the pipeline never crashes on enrichment failure.
    customer_profile: dict[str, Any] | None
