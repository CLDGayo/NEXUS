"""LangGraph state schema for the Nexus v2 cortex.

A single TypedDict shared by every node. Optional fields are populated as
the graph traverses; only ``query``, ``thread_key``, ``correlation_id``,
and ``surface`` are required at entry.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from rag.retrieval.types import ScoredChunk

Surface = Literal["messenger", "spa", "test"]


class NexusState(TypedDict, total=False):
    # Entry fields (set by the webhook adapter)
    query: str
    thread_key: str
    correlation_id: str
    surface: Surface

    # Retrieval pipeline outputs
    dense_hits: list[ScoredChunk]
    sparse_hits: list[ScoredChunk]
    fused: list[ScoredChunk]
    reranked: list[ScoredChunk]

    # Generation + validation
    answer: str
    citations: tuple[str, ...]
    guardrail_passed: bool
    guardrail_reason: str | None

    # Bookkeeping
    abstained: bool
