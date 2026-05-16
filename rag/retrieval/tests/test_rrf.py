"""Pure-math tests for Reciprocal Rank Fusion.

Asserts the exact formula ``score(d) = Σ 1/(k + rank_r(d))`` with ``k=60``
and verifies the algorithm's published properties: rank-only (score
distributions are irrelevant), deterministic merge, and tie-breaking by
descending fused score.
"""

from __future__ import annotations

from math import isclose

import pytest

from rag.retrieval.rrf import DEFAULT_K, reciprocal_rank_fusion
from rag.retrieval.types import ScoredChunk


def chunk(id_: str, score: float = 0.0) -> ScoredChunk:
    return ScoredChunk(id=id_, text=f"text-{id_}", score=score)


@pytest.mark.unit
def test_default_k_is_60() -> None:
    assert DEFAULT_K == 60


@pytest.mark.unit
def test_empty_input_returns_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


@pytest.mark.unit
def test_single_arm_preserves_rank_order() -> None:
    arm = [chunk("a"), chunk("b"), chunk("c")]
    fused = reciprocal_rank_fusion([arm])
    assert [c.id for c in fused] == ["a", "b", "c"]
    # rank 1 → 1/(60+1), rank 2 → 1/(60+2), rank 3 → 1/(60+3)
    assert isclose(fused[0].score, 1 / 61, rel_tol=1e-9)
    assert isclose(fused[1].score, 1 / 62, rel_tol=1e-9)
    assert isclose(fused[2].score, 1 / 63, rel_tol=1e-9)


@pytest.mark.unit
def test_two_arm_fusion_summation() -> None:
    """Document appears in both arms at different ranks — scores sum."""

    dense = [chunk("a"), chunk("b"), chunk("c")]  # a:1, b:2, c:3
    sparse = [chunk("b"), chunk("a"), chunk("d")]  # b:1, a:2, d:3
    fused = reciprocal_rank_fusion([dense, sparse])

    expected = {
        "a": 1 / 61 + 1 / 62,
        "b": 1 / 62 + 1 / 61,
        "c": 1 / 63,
        "d": 1 / 63,
    }
    scores = {c.id: c.score for c in fused}
    for key, want in expected.items():
        assert isclose(scores[key], want, rel_tol=1e-9), f"score for {key}"


@pytest.mark.unit
def test_fusion_sorted_descending() -> None:
    dense = [chunk(letter) for letter in "abcde"]
    sparse = [chunk(letter) for letter in "edcba"]
    fused = reciprocal_rank_fusion([dense, sparse])
    scores = [c.score for c in fused]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.unit
def test_consistent_midrank_beats_single_arm_top() -> None:
    """RRF property: a doc ranked mid in many arms beats a doc ranked #1 in one."""

    arm_a = [chunk("only_a"), chunk("shared"), chunk("filler1")]
    arm_b = [chunk("shared"), chunk("only_b"), chunk("filler2")]
    arm_c = [chunk("shared"), chunk("only_c"), chunk("filler3")]

    fused = reciprocal_rank_fusion([arm_a, arm_b, arm_c])
    top = fused[0]
    assert top.id == "shared", (
        "doc that consistently ranks across 3 arms must beat 1-arm leaders"
    )


@pytest.mark.unit
def test_rejects_invalid_k() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[chunk("a")]], k=0)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[chunk("a")]], k=-1)


@pytest.mark.unit
def test_custom_k_changes_score_but_not_order() -> None:
    arm = [chunk("a"), chunk("b"), chunk("c")]
    k60 = reciprocal_rank_fusion([arm], k=60)
    k10 = reciprocal_rank_fusion([arm], k=10)
    assert [c.id for c in k60] == [c.id for c in k10]
    assert k10[0].score > k60[0].score  # smaller k → larger reciprocals


@pytest.mark.unit
def test_metadata_preserved_from_first_occurrence() -> None:
    a_first = ScoredChunk(id="a", text="t1", score=0.0, metadata={"src": "arm1"})
    a_second = ScoredChunk(id="a", text="t1", score=0.0, metadata={"src": "arm2"})
    fused = reciprocal_rank_fusion([[a_first], [a_second]])
    assert len(fused) == 1
    assert fused[0].metadata["src"] == "arm1"
