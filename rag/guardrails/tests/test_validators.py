"""Phase 5 validator suite tests."""

from __future__ import annotations

import pytest

from rag.guardrails.validators import (
    CitationValidator,
    ExactMatchValidator,
    ValidationResult,
)
from rag.retrieval.types import ScoredChunk


def chunk(text: str, id_: str = "c") -> ScoredChunk:
    return ScoredChunk(id=id_, text=text, score=1.0)


# ---------------------------------------------------------------------------
# ValidationResult basics
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_validation_result_failed_property() -> None:
    ok = ValidationResult(name="x", passed=True)
    bad = ValidationResult(name="x", passed=False, reason="bad")
    assert not ok.failed
    assert bad.failed


# ---------------------------------------------------------------------------
# CitationValidator
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCitationValidator:
    def test_passes_with_valid_citations(self) -> None:
        v = CitationValidator()
        retrieved = [chunk("our plan", "a"), chunk("includes onboarding", "b")]
        r = v.validate("Plan [1] includes onboarding [2].", retrieved=retrieved)
        assert r.passed
        assert r.metadata["cited_ids"] == ["a", "b"]

    def test_fails_with_no_citations(self) -> None:
        v = CitationValidator()
        retrieved = [chunk("pricing"), chunk("plan")]
        r = v.validate("Our pricing is $99/month.", retrieved=retrieved)
        assert r.failed
        assert "citations" in (r.reason or "")

    def test_passes_on_abstention_with_no_context(self) -> None:
        v = CitationValidator()
        r = v.validate(
            "I don't have that information; want me to route you to a human?",
            retrieved=[],
        )
        assert r.passed


# ---------------------------------------------------------------------------
# ExactMatchValidator
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExactMatchValidator:
    def test_empty_answer_fails(self) -> None:
        v = ExactMatchValidator()
        r = v.validate("", retrieved=[chunk("anything")])
        assert r.failed
        assert "empty" in (r.reason or "").lower()

    def test_no_context_passes_to_defer_to_citation(self) -> None:
        v = ExactMatchValidator()
        r = v.validate("Anything goes here.", retrieved=[])
        assert r.passed

    def test_passes_when_numbers_present_in_context(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("our plan starts at $99 per month including onboarding")]
        r = v.validate("Plan starts at $99 per month [1].", retrieved=retrieved)
        assert r.passed

    def test_fails_on_fabricated_price(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("our plan starts at $99 per month")]
        r = v.validate("Plan is $147.99 per month [1].", retrieved=retrieved)
        assert r.failed
        suspicious = [s["token"] for s in r.metadata["suspicious"]]
        assert any("147" in t for t in suspicious)

    def test_fails_on_fabricated_proper_noun(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("we work with ACME Industries on projects")]
        r = v.validate(
            "We work with FakeCorp on critical projects [1].", retrieved=retrieved
        )
        assert r.failed
        suspicious = [s["token"] for s in r.metadata["suspicious"]]
        assert "FakeCorp" in suspicious

    def test_allowlist_skips_pronouns(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("we ship orders")]
        r = v.validate("We ship orders. Our team handles it.", retrieved=retrieved)
        assert r.passed, f"unexpected fail: {r.reason}"

    def test_allowlist_matches_case_insensitively(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("we ship orders")]
        r = v.validate(
            "We ship orders. YES we deliver. OK to proceed.", retrieved=retrieved
        )
        assert r.passed, f"unexpected fail: {r.reason}"

    def test_hyphenated_compound_split_for_match(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("retrieval augmented generation is the core pattern")]
        r = v.validate(
            "Our system uses Retrieval-Augmented Generation [1].",
            retrieved=retrieved,
        )
        assert r.passed, f"unexpected fail: {r.reason}"

    def test_apostrophe_contraction_does_not_create_proper_noun(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("we route to a human agent")]
        r = v.validate(
            "I'll route you to a human agent.", retrieved=retrieved
        )
        assert r.passed, f"unexpected fail: {r.reason}"

    def test_passes_when_proper_noun_in_context(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("acme industries is a partner")]
        r = v.validate(
            "Our partner Acme handles fulfillment [1].", retrieved=retrieved
        )
        assert r.passed

    def test_commas_in_numbers_not_a_mismatch(self) -> None:
        v = ExactMatchValidator()
        retrieved = [chunk("priced at 1,499 per seat per year")]
        r = v.validate("Priced at $1,499 per seat [1].", retrieved=retrieved)
        # "1,499" → normalized "1499" → matches digits_blob "1499"
        assert r.passed
