"""Reciprocal Rank Fusion.

Implements the weighted summation from the Nexus architecture brief:

    score(d) = Σ_r W_r · 1 / (k + rank_r(d))

where ``r`` iterates over each independent retrieval arm, ``rank_r(d)`` is
the 1-indexed position of document ``d`` in arm ``r``'s ranking, and
``W_r`` is the per-arm weight multiplier (defaults to ``1.0`` so omitting
weights collapses to the standard unweighted formula).

``k=60`` is the standard smoothing constant (Cormack et al. 2009) and is
the default for this implementation.

RRF is rank-based rather than score-based, which is why we can fuse the
dense (cosine 0..1) and sparse (BM25 unbounded) arms without normalizing
their incompatible score distributions.

Phase 25 — to weight by arm, callers pass ``rankings`` as a mapping from
arm name to ranked list (e.g. ``{"dense": [...], "sparse": [...]}``) and a
parallel ``weights`` mapping. The legacy positional form (an iterable of
ranked lists) is still accepted unchanged for backward compatibility but
rejects any non-``None`` ``weights`` argument so a caller that wants
weighting is forced to supply arm identities.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Union

from rag.retrieval.types import ScoredChunk

DEFAULT_K: int = 60

Rankings = Union[
    Iterable[list[ScoredChunk]],
    Mapping[str, list[ScoredChunk]],
]


def reciprocal_rank_fusion(
    rankings: Rankings,
    *,
    k: int = DEFAULT_K,
    weights: Mapping[str, float] | None = None,
) -> list[ScoredChunk]:
    """Merge multiple ranked lists by weighted reciprocal-rank summation.

    Args:
        rankings: Either a mapping ``{arm_name: ranked_list}`` (required
            when ``weights`` is provided) or an iterable of ranked lists
            (legacy positional form, treated as unweighted). Order within
            each ranked list is significant; the first element is rank 1.
        k: Smoothing constant. Higher values dampen the influence of
            top-ranked items, raising the value of consistent mid-rank
            consensus across arms. Defaults to ``60``.
        weights: Optional mapping ``{arm_name: weight}``. Arms missing
            from this map default to ``1.0``. Zero is allowed (the arm
            contributes nothing this query). Negative weights raise
            ``ValueError`` — they would invert ranking and are almost
            certainly a bug. Requires ``rankings`` to be a ``Mapping``.

    Returns:
        A single list of ``ScoredChunk`` instances ordered by descending
        fused score. Chunks that appear in multiple input rankings are
        merged once; their ``text`` and ``metadata`` are taken from the
        first occurrence to keep results deterministic.

    Raises:
        ValueError: ``k < 1``, any weight ``< 0``, or ``weights`` passed
            alongside positional ``rankings`` (no arm identities to bind
            the weights to).
    """

    if k < 1:
        raise ValueError(f"RRF smoothing constant k must be >= 1; got {k}")

    if weights is not None:
        for arm, w in weights.items():
            if w < 0:
                raise ValueError(
                    f"RRF weight for arm {arm!r} must be >= 0; got {w}"
                )
        if not isinstance(rankings, Mapping):
            raise ValueError(
                "weights requires named rankings; pass rankings as a "
                "Mapping[str, list[ScoredChunk]] when supplying weights"
            )

    fused: dict[str, tuple[ScoredChunk, float]] = {}

    if isinstance(rankings, Mapping):
        items: Iterable[tuple[str | None, list[ScoredChunk]]] = (
            (name, ranking) for name, ranking in rankings.items()
        )
    else:
        items = ((None, ranking) for ranking in rankings)

    for arm_name, ranking in items:
        weight = (
            weights.get(arm_name, 1.0)
            if weights is not None and arm_name is not None
            else 1.0
        )
        if weight == 0.0:
            continue
        for rank, chunk in enumerate(ranking, start=1):
            increment = weight * (1.0 / (k + rank))
            if chunk.id in fused:
                existing_chunk, existing_score = fused[chunk.id]
                fused[chunk.id] = (existing_chunk, existing_score + increment)
            else:
                fused[chunk.id] = (chunk, increment)

    merged = [chunk.with_score(score) for chunk, score in fused.values()]
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged
