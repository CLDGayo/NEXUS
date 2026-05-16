"""Phase 3 groundedness validator tests."""

from __future__ import annotations

import pytest

from rag.guardrails.groundedness import (
    abstention_text,
    check_groundedness,
)
from rag.retrieval.types import ScoredChunk


def ctx(*ids: str) -> list[ScoredChunk]:
    return [ScoredChunk(id=i, text=f"text-{i}", score=1.0) for i in ids]


@pytest.mark.unit
class TestEmpty:
    def test_empty_answer_fails(self) -> None:
        result = check_groundedness("", ctx("a"))
        assert result.failed
        assert result.reason == "empty answer"

    def test_whitespace_answer_fails(self) -> None:
        result = check_groundedness("   \n  ", ctx("a"))
        assert result.failed


@pytest.mark.unit
class TestNoContext:
    def test_no_context_assertion_fails(self) -> None:
        result = check_groundedness("Our pricing starts at $99/month.", [])
        assert result.failed
        assert "no retrieved context" in (result.reason or "")

    def test_no_context_abstention_passes(self) -> None:
        result = check_groundedness(
            "I don't have information on that. Want me to route you to a human?",
            [],
        )
        assert result.passed
        assert result.cited_ids == ()


@pytest.mark.unit
class TestCitations:
    def test_missing_citations_fails(self) -> None:
        result = check_groundedness(
            "Our pricing starts at $99/month.", ctx("a", "b")
        )
        assert result.failed
        assert "without citations" in (result.reason or "")

    def test_valid_citations_pass(self) -> None:
        result = check_groundedness(
            "Pricing starts at $99/month [1] and includes onboarding [2].",
            ctx("a", "b"),
        )
        assert result.passed
        assert result.cited_ids == ("a", "b")

    def test_repeated_citation_dedup(self) -> None:
        result = check_groundedness(
            "Plan [1] includes feature X [1] and feature Y [1].", ctx("a")
        )
        assert result.passed
        assert result.cited_ids == ("a",)

    def test_out_of_range_citation_fails(self) -> None:
        result = check_groundedness(
            "Pricing is $99 [3].", ctx("a", "b")
        )
        assert result.failed
        assert "exceed" in (result.reason or "")

    def test_abstention_without_citation_still_passes(self) -> None:
        result = check_groundedness(
            "I don't have that information in our knowledge base.",
            ctx("a", "b"),
        )
        assert result.passed


@pytest.mark.unit
def test_abstention_text_is_constant() -> None:
    text = abstention_text()
    assert text == abstention_text()
    assert "human agent" in text.lower() or "route" in text.lower()
