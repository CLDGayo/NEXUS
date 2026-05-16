"""Reciprocal Rank Fusion.

Implements the mathematical summation from the Nexus architecture brief:

    score(d) = Σ_r 1 / (k + rank_r(d))

where ``r`` iterates over each independent retrieval arm and ``rank_r(d)``
is the 1-indexed position of document ``d`` in arm ``r``'s ranking.
``k=60`` is the standard smoothing constant (Cormack et al. 2009) and is
the default for this implementation.

RRF is rank-based rather than score-based, which is why we can fuse the
dense (cosine 0..1) and sparse (BM25 unbounded) arms without normalizing
their incompatible score distributions.
"""

from __future__ import annotations

from collections.abc import Iterable

from rag.retrieval.types import ScoredChunk

DEFAULT_K: int = 60


def reciprocal_rank_fusion(
    rankings: Iterable[list[ScoredChunk]],
    *,
    k: int = DEFAULT_K,
) -> list[ScoredChunk]:
    """Merge multiple ranked lists by reciprocal-rank summation.

    Args:
        rankings: An iterable of ranked lists. Order within each list is
            significant; the first element is rank 1.
        k: Smoothing constant. Higher values dampen the influence of
            top-ranked items, raising the value of consistent mid-rank
            consensus across arms. Defaults to ``60``.

    Returns:
        A single list of ``ScoredChunk`` instances ordered by descending
        fused score. Chunks that appear in multiple input rankings are
        merged once; their ``text`` and ``metadata`` are taken from the
        first occurrence to keep results deterministic.
    """

    if k < 1:
        raise ValueError(f"RRF smoothing constant k must be >= 1; got {k}")

    fused: dict[str, tuple[ScoredChunk, float]] = {}

    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            increment = 1.0 / (k + rank)
            if chunk.id in fused:
                existing_chunk, existing_score = fused[chunk.id]
                fused[chunk.id] = (existing_chunk, existing_score + increment)
            else:
                fused[chunk.id] = (chunk, increment)

    merged = [chunk.with_score(score) for chunk, score in fused.values()]
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged
