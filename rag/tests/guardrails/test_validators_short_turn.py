"""Phase 19.1 guardrail relaxation regression tests.

Production logs (2026-05-21) showed conversational Messenger turns being
blocked by ``ExactMatchValidator`` because a sibling retrieved chunk
introduced a proper noun absent from the answer's literal context. These
tests pin the new behavior: short turns bypass exact-match, metadata is
treated as real context, and the user query is folded into the context blob.
"""

from __future__ import annotations

import pytest

from rag.guardrails.pipeline import GuardrailsPipeline, default_pipeline
from rag.guardrails.validators import (
    CitationValidator,
    ExactMatchValidator,
)
from rag.retrieval.types import ScoredChunk


def _chunk(
    text: str,
    *,
    id: str = "c1",
    score: float = 1.0,
    metadata: dict | None = None,
) -> ScoredChunk:
    return ScoredChunk(
        id=id, text=text, score=score, metadata=metadata or {}
    )


# ---------------------------------------------------------------------------
# ExactMatchValidator default tolerance
# ---------------------------------------------------------------------------

class TestExactMatchTolerance:
    """``max_suspicious=2`` so one bled-in proper noun no longer blocks."""

    def test_one_unverified_proper_noun_passes(self) -> None:
        v = ExactMatchValidator()
        # "Gwyn" is fabricated; "Clarence" is owner-identity allowlist; ergo
        # exactly one suspicious token. Under max_suspicious=2 this passes.
        chunks = [_chunk("Some unrelated retrieved text.")]
        result = v.validate(
            "Hello, said Gwyn yesterday.", retrieved=chunks
        )
        assert result.passed, result.reason

    def test_three_unverified_proper_nouns_fails(self) -> None:
        v = ExactMatchValidator()
        chunks = [_chunk("Unrelated retrieved text.")]
        # Validator skips sentence-initial capitalized words (always cap),
        # so we need 3 NON-initial proper nouns to trigger failure.
        result = v.validate(
            "Yesterday Gwyn met Bartholomew and Persephone.",
            retrieved=chunks,
        )
        assert not result.passed
        # Reason carries the count for debugging.
        assert "3 suspicious" in (result.reason or "")

    def test_owner_identity_words_are_allowlisted(self) -> None:
        v = ExactMatchValidator()
        chunks = [_chunk("Unrelated retrieved text.")]
        result = v.validate(
            "Welcome to Nexus, Clarence. Gayo Sphere is online.",
            retrieved=chunks,
        )
        assert result.passed, result.reason


# ---------------------------------------------------------------------------
# Query + metadata threading
# ---------------------------------------------------------------------------

class TestExtendedContext:
    """User query and chunk metadata should count as retrieved context."""

    def test_user_query_makes_self_intro_non_suspicious(self) -> None:
        v = ExactMatchValidator()
        chunks = [_chunk("Vault note about productivity.")]
        result = v.validate(
            "Nice to meet you, Aldous.",
            retrieved=chunks,
            query="I am Aldous and this is my picture.",
        )
        assert result.passed, result.reason

    def test_alias_in_metadata_treated_as_context(self) -> None:
        v = ExactMatchValidator()
        chunks = [
            _chunk(
                "A note body that does not mention the alias.",
                metadata={"aliases": ["Brontes"], "title": "BronteEntity"},
            )
        ]
        result = v.validate(
            "Brontes wrote three things yesterday.",
            retrieved=chunks,
        )
        assert result.passed, result.reason

    def test_title_in_metadata_treated_as_context(self) -> None:
        v = ExactMatchValidator()
        chunks = [
            _chunk(
                "Body text only references the topic abstractly.",
                metadata={"title": "Cassandra Project Brief"},
            )
        ]
        result = v.validate(
            "Cassandra ships in Q3.",
            retrieved=chunks,
        )
        assert result.passed, result.reason


# ---------------------------------------------------------------------------
# Short-turn bypass at the pipeline layer
# ---------------------------------------------------------------------------

class TestShortTurnBypass:
    """A 1-3 token query + <=30 token answer skips exact-match entirely."""

    def test_greeting_skips_exact_match(self) -> None:
        pipeline = GuardrailsPipeline(validators=(ExactMatchValidator(),))
        chunks = [_chunk("Unrelated retrieved text.")]
        result = pipeline.validate(
            "Hello [1]! Mortimer here.",
            retrieved=chunks,
            query="hi",
        )
        em = next(r for r in result.results if r.name == "exact_match")
        assert em.passed
        assert em.metadata.get("bypassed") is True

    def test_short_query_long_answer_runs_validator(self) -> None:
        pipeline = GuardrailsPipeline(validators=(ExactMatchValidator(),))
        chunks = [_chunk("Unrelated retrieved text.")]
        # 31 words triggers full run because the answer is no longer terse.
        long_answer = " ".join(
            ["This"]
            + ["filler"] * 28
            + ["Gwyn", "Aldous", "Persephone"]  # 3 suspicious
        )
        result = pipeline.validate(
            long_answer, retrieved=chunks, query="hi"
        )
        em = next(r for r in result.results if r.name == "exact_match")
        assert em.metadata.get("bypassed") is not True
        assert not em.passed

    def test_long_query_short_answer_runs_validator(self) -> None:
        pipeline = GuardrailsPipeline(validators=(ExactMatchValidator(),))
        chunks = [_chunk("Unrelated retrieved text.")]
        # Three non-sentence-initial proper nouns in a single sentence.
        result = pipeline.validate(
            "Yesterday Gwyn met Bartholomew and Persephone.",
            retrieved=chunks,
            query="who are the three people you mentioned earlier",
        )
        em = next(r for r in result.results if r.name == "exact_match")
        assert em.metadata.get("bypassed") is not True
        assert not em.passed

    def test_empty_query_does_not_bypass(self) -> None:
        # Guard: if state.get("query","") is empty (eg internal call),
        # don't silently disable exact-match.
        pipeline = GuardrailsPipeline(validators=(ExactMatchValidator(),))
        chunks = [_chunk("Unrelated retrieved text.")]
        result = pipeline.validate(
            "Hello Mortimer Mortimer Mortimer.",
            retrieved=chunks,
            query="",
        )
        em = next(r for r in result.results if r.name == "exact_match")
        assert em.metadata.get("bypassed") is not True


# ---------------------------------------------------------------------------
# Pipeline integration smoke
# ---------------------------------------------------------------------------

class TestDefaultPipelineGreeting:
    """End-to-end: the exact Messenger scenario from the 05-21 log dump."""

    def test_hi_greeting_with_bled_in_entity_passes(self) -> None:
        pipeline = default_pipeline()
        chunks = [
            _chunk(
                "Gwyn is a vault contact noted on 2025-11-04.",
                metadata={"title": "Gwyn", "aliases": ["G."], "tags": ["person"]},
            )
        ]
        # Short turn → exact_match bypassed; citation gates on cited [n]s
        # not entity recognition; entropy is lenient on short greetings.
        # Use a citationless terse acknowledgement; CitationValidator only
        # fails on factual claims, not greetings — confirm it doesn't block.
        result = pipeline.validate(
            "Hi! Happy to help — what would you like to chat about?",
            retrieved=chunks,
            query="hi",
        )
        # We don't assert passed=True (citation behavior is a separate
        # contract); we assert exact_match is NOT the blocker.
        em = next(r for r in result.results if r.name == "exact_match")
        assert em.passed, em.reason


# ---------------------------------------------------------------------------
# Citation + Entropy still accept the new kwargs (Protocol conformance)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "validator_cls",
    [CitationValidator, ExactMatchValidator],
)
def test_validators_accept_query_kwarg(validator_cls) -> None:
    v = validator_cls()
    chunks = [_chunk("any text")]
    # Should not raise TypeError despite some validators ignoring `query`.
    v.validate("Some answer [1]", retrieved=chunks, query="anything")
