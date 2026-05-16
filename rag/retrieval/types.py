"""Shared retrieval data types.

The pipeline passes ``ScoredChunk`` instances between every stage so each
arm produces the same shape and the fuser/reranker stays algorithm-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScoredChunk:
    """One retrieved chunk with its provenance and current relevance score.

    ``score`` semantics differ per stage:
        - dense arm  → cosine similarity (Qdrant, 0..1)
        - sparse arm → BM25 score (unbounded, corpus-relative)
        - RRF        → reciprocal rank sum (Σ 1/(k+rank), bounded by arm count)
        - reranker   → cross-encoder logit (model-specific scale)

    Callers should not mix scores across stages; each stage produces a new
    ``ScoredChunk`` with its own score.
    """

    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_score(self, new_score: float) -> "ScoredChunk":
        return ScoredChunk(
            id=self.id, text=self.text, score=new_score, metadata=self.metadata
        )
