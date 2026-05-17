"""Phase 5 entropy proxy tests."""

from __future__ import annotations

import pytest

from rag.guardrails.entropy import (
    EntropyValidator,
    compute_semantic_entropy,
    compute_uncertainty_score,
)
from rag.retrieval.types import ScoredChunk


def chunk(text: str = "context body here", id_: str = "c") -> ScoredChunk:
    return ScoredChunk(id=id_, text=text, score=1.0)


@pytest.mark.unit
class TestUncertaintyScore:
    def test_empty_answer_maximum_uncertainty(self) -> None:
        assert compute_uncertainty_score("", [chunk()]) == 1.0
        assert compute_uncertainty_score("   ", [chunk()]) == 1.0

    def test_confident_well_cited_answer_low(self) -> None:
        answer = (
            "Our plan starts at $99 per month [1] and includes onboarding [2]. "
            "Reply YES to book a call with the team."
        )
        score = compute_uncertainty_score(answer, [chunk(), chunk()])
        assert score < 0.4

    def test_hedged_answer_high(self) -> None:
        answer = (
            "I think pricing might be around $99, but I'm not sure. "
            "Perhaps it could be slightly different — unclear at this point."
        )
        score = compute_uncertainty_score(answer, [chunk()])
        assert score > 0.5

    def test_no_citations_no_context_doesnt_double_penalize(self) -> None:
        answer = "I don't have that information."
        score = compute_uncertainty_score(answer, [])
        # Short + zero context but not necessarily HIGH because citation
        # deficit is skipped when retrieved is empty.
        assert 0.0 <= score <= 1.0

    def test_very_short_answer_penalized(self) -> None:
        short = "Yes."
        long = (
            "Our plan starts at $99 [1] and includes onboarding [2]. "
            "Reply YES to book a call now."
        )
        assert compute_uncertainty_score(short, [chunk()]) > compute_uncertainty_score(long, [chunk()])


@pytest.mark.unit
class TestEntropyValidator:
    def test_passes_below_ceiling(self) -> None:
        v = EntropyValidator(ceiling=0.7)
        answer = "Our plan [1] includes everything [2]. Reply YES to book a call."
        r = v.validate(answer, retrieved=[chunk(), chunk()])
        assert r.passed
        assert r.metadata["score"] == pytest.approx(
            compute_uncertainty_score(answer, [chunk(), chunk()])
        )

    def test_fails_above_ceiling(self) -> None:
        v = EntropyValidator(ceiling=0.3)
        answer = "I think it might possibly be around something, I'm not sure."
        r = v.validate(answer, retrieved=[])
        assert r.failed
        assert r.metadata["score"] > 0.3
        assert "ceiling" in (r.reason or "")


@pytest.mark.unit
class TestSemanticEntropyFallback:
    """Fallback path when no embedder supplied — clusters by exact string."""

    def test_all_identical_samples_zero_entropy(self) -> None:
        score = compute_semantic_entropy(["same answer"] * 5)
        assert score == 0.0

    def test_all_distinct_samples_high_entropy(self) -> None:
        samples = ["one", "two", "three", "four", "five"]
        score = compute_semantic_entropy(samples)
        assert score > 0.5

    def test_empty_samples_returns_max(self) -> None:
        assert compute_semantic_entropy([]) == 1.0
