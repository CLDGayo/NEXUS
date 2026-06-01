"""Phase 5 GuardrailsPipeline tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rag.guardrails.pipeline import (
    GuardrailsPipeline,
    default_pipeline,
)
from rag.guardrails.validators import ValidationResult
from rag.retrieval.types import ScoredChunk


def chunk(text: str = "context body") -> ScoredChunk:
    return ScoredChunk(id="c", text=text, score=1.0)


@dataclass
class _StubValidator:
    name: str
    result: ValidationResult

    def validate(self, answer: str, *, retrieved, **_kwargs):
        return self.result


@pytest.mark.unit
class TestPipelineAggregation:
    def test_all_pass(self) -> None:
        pipeline = GuardrailsPipeline(
            validators=(
                _StubValidator("a", ValidationResult(name="a", passed=True)),
                _StubValidator("b", ValidationResult(name="b", passed=True)),
            )
        )
        out = pipeline.validate("any answer", retrieved=[chunk()])
        assert out.passed
        assert not out.blocked
        assert not out.requires_handover
        assert out.fallback_text is None
        assert out.failed_names == ()

    def test_critical_fail_blocks_and_triggers_handover(self) -> None:
        pipeline = GuardrailsPipeline(
            validators=(
                _StubValidator(
                    "a",
                    ValidationResult(
                        name="a", passed=False, reason="bad", severity="critical"
                    ),
                ),
            )
        )
        out = pipeline.validate("any", retrieved=[chunk()])
        assert out.blocked
        assert out.requires_handover
        assert out.fallback_text  # deterministic fallback string
        assert "a" in out.failed_names

    def test_warning_fail_does_not_block(self) -> None:
        pipeline = GuardrailsPipeline(
            validators=(
                _StubValidator(
                    "a",
                    ValidationResult(
                        name="a", passed=False, reason="meh", severity="warning"
                    ),
                ),
            )
        )
        out = pipeline.validate("any", retrieved=[chunk()])
        assert not out.blocked
        assert not out.requires_handover
        assert out.warnings and out.warnings[0].name == "a"

    def test_validator_exception_treated_as_critical_fail(self) -> None:
        class _Boom:
            name = "boom"

            def validate(self, *args, **kwargs):
                raise RuntimeError("simulated")

        pipeline = GuardrailsPipeline(validators=(_Boom(),))
        out = pipeline.validate("any", retrieved=[chunk()])
        assert out.blocked
        assert "boom" in out.failed_names

    def test_uncertainty_score_always_included(self) -> None:
        pipeline = GuardrailsPipeline(validators=())
        out = pipeline.validate("anything", retrieved=[chunk()])
        assert 0.0 <= out.uncertainty_score <= 1.0


@pytest.mark.unit
class TestDefaultPipeline:
    """Sanity smoke for the production pipeline composition."""

    def test_fully_grounded_passes(self) -> None:
        pipeline = default_pipeline()
        retrieved = [
            ScoredChunk(id="a", text="our plan starts at $99 per month", score=1.0),
            ScoredChunk(id="b", text="includes onboarding for new clients", score=1.0),
        ]
        answer = "Plan starts at $99 [1] and includes onboarding [2]."
        out = pipeline.validate(answer, retrieved=retrieved)
        assert not out.blocked, (
            f"failures: {[r.reason for r in out.results if r.failed]}"
        )

    def test_fabricated_prices_block_when_count_exceeds_tolerance(self) -> None:
        # Default pipeline now tolerates up to 2 unverified specifics
        # (Phase 19.1 — relaxed from 0). Confirm 3 fabrications still block.
        pipeline = default_pipeline()
        retrieved = [ScoredChunk(id="a", text="our plan starts at $99", score=1.0)]
        # Long enough answer so the short-turn bypass doesn't kick in.
        answer = (
            "The plan starts at $147.99 [1], rises to $258.50 [1], and "
            "doubles to $911.42 [1] in year three when we apply the "
            "contractual escalator described above."
        )
        # Query > 8 tokens so the short-turn bypass doesn't skip exact_match.
        out = pipeline.validate(
            answer,
            retrieved=retrieved,
            query="tell me about all of the annual pricing tiers in detail please",
        )
        assert out.blocked
        assert "exact_match" in out.failed_names

    def test_uncited_factual_claim_blocks(self) -> None:
        pipeline = default_pipeline()
        retrieved = [ScoredChunk(id="a", text="our plan", score=1.0)]
        answer = "Plan starts at $99."  # no [n] citation
        out = pipeline.validate(answer, retrieved=retrieved)
        assert out.blocked
        assert "citation" in out.failed_names

    def test_high_uncertainty_blocks(self) -> None:
        pipeline = default_pipeline()
        retrieved = [ScoredChunk(id="a", text="anything", score=1.0)]
        # Heavily hedged + uncited + short.
        answer = "I think maybe possibly."
        out = pipeline.validate(answer, retrieved=retrieved)
        assert out.blocked


@pytest.mark.unit
class TestSurfaceAwareThreshold:
    """Phase 33.1 — Messenger surface gets a relaxed exact_match
    threshold so the SDR persona's conversational CTAs don't trigger
    false positives. SPA stays strict."""

    _RETRIEVED = [ScoredChunk(id="a", text="Phase 33 ships the SDR.", score=1.0)]
    # Four suspicious tokens (Monkey, Luffy, Piece, Mortimer) — close to
    # the exact production failure that prompted this hotfix. ("One"
    # falls below the >=3-char proper-noun regex; "Would" is now
    # allowlisted via Phase 33.1 Fix 1a.)
    _ANSWER = (
        "We have Monkey D. Luffy from One Piece in stock [1]. "
        "Mortimer can ship today — would you like a checkout link?"
    )
    _QUERY = "Do you have Luffy gear 4 in stock right now please?"

    def test_messenger_tolerates_up_to_five_suspicious_tokens(self) -> None:
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="messenger",
        )
        assert not out.blocked, (
            "messenger should tolerate ≤5 suspicious tokens; got "
            f"failed={out.failed_names} reasons={[r.reason for r in out.results if r.failed]}"
        )

    def test_spa_stays_strict_on_suspicious_tokens(self) -> None:
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="spa",
        )
        assert out.blocked, "SPA should still block on >2 suspicious tokens"
        assert "exact_match" in out.failed_names

    def test_pipeline_restores_max_suspicious_after_messenger_call(self) -> None:
        """The save/restore must run — pipeline is a module-level
        singleton in production via ``_GUARDRAILS = default_pipeline()``
        in ``rag/orchestrator/nodes.py``; a leaked mutation would
        permanently relax SPA after the first Messenger request."""
        pipeline = default_pipeline()
        em = next(
            v for v in pipeline.validators if getattr(v, "name", "") == "exact_match"
        )
        original = em.max_suspicious  # type: ignore[attr-defined]
        pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="messenger",
        )
        assert em.max_suspicious == original, (  # type: ignore[attr-defined]
            "pipeline leaked max_suspicious mutation across the call"
        )


@pytest.mark.unit
class TestVisionPathCitationBypass:
    """Phase 33.2 — Messenger vision path bypasses ``CitationValidator``.

    The vision model hallucinates out-of-bounds ``[n]`` indices. Grounding
    on the vision path is the image + product_branch catalog injection,
    not RAG citation indices, so the bypass doesn't relax factual safety.
    ``exact_match`` and ``entropy`` still run.
    """

    _RETRIEVED = [
        ScoredChunk(id=f"c{i}", text=f"chunk {i} body", score=1.0 / i)
        for i in range(1, 5)  # 4 chunks → indices [1]..[4] valid; [11] not
    ]
    # Long enough that the short-turn bypass doesn't fire (>40 words).
    _ANSWER = (
        "Yes [11], we have Luffy Gear 4 in stock right now and it's a "
        "fantastic piece for any serious collector — would you like me to "
        "send you a checkout link or check stock at the other warehouse "
        "before we lock it in? Happy to help either way."
    )
    # Multi-word query so the short-turn bypass doesn't apply.
    _QUERY = "Do you have Luffy gear 4 figurine in stock right now please?"

    def test_messenger_vision_bypasses_citation(self) -> None:
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="messenger",
            has_attachments=True,
        )
        assert not out.blocked, (
            "vision path should bypass citation; got "
            f"failed={out.failed_names} reasons={[r.reason for r in out.results if r.failed]}"
        )
        citation_result = next(r for r in out.results if r.name == "citation")
        assert citation_result.passed
        assert citation_result.reason == "vision-path bypass"
        assert citation_result.metadata.get("bypassed") is True

    def test_messenger_vision_bypass_extracts_valid_cited_ids_only(self) -> None:
        """Out-of-bounds [11] is dropped; in-bounds [1] is preserved so
        the Messenger surface adapter can still render source tags."""
        pipeline = default_pipeline()
        answer = (
            "Confirmed [1], we have Luffy Gear 4 [11] available — would "
            "you like a checkout link? Mortimer can ship today and we'll "
            "include the bonus base plate just for early buyers like you."
        )
        out = pipeline.validate(
            answer,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="messenger",
            has_attachments=True,
        )
        citation_result = next(r for r in out.results if r.name == "citation")
        cited_ids = citation_result.metadata.get("cited_ids")
        assert cited_ids == ["c1"], f"expected only in-bounds [1]→c1; got {cited_ids}"

    def test_messenger_text_only_does_not_bypass_citation(self) -> None:
        """``has_attachments=False`` → CitationValidator runs in full and
        the out-of-bounds [11] blocks the answer. This pins that the
        bypass is gated on attachments, not surface alone."""
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="messenger",
            has_attachments=False,
        )
        assert out.blocked
        assert "citation" in out.failed_names

    def test_spa_vision_does_not_bypass_citation(self) -> None:
        """``surface="spa"`` → bypass does NOT trigger even with
        attachments. SPA is the strict surface."""
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=self._RETRIEVED,
            query=self._QUERY,
            surface="spa",
            has_attachments=True,
        )
        assert out.blocked
        assert "citation" in out.failed_names


@pytest.mark.unit
class TestCatalogTextThreading:
    """Phase 33.3 — ``guardrails_node`` threads ``[Product Catalog Match]``
    chunk text into the validator's ``query`` so anime / franchise proper
    nouns inside product names ("King", "Artist", "Special", "Version")
    don't trigger ExactMatchValidator false positives that previously
    sent legitimate SDR responses to the human-handover fallback.
    """

    def test_catalog_proper_nouns_threaded_via_query_are_not_suspicious(self) -> None:
        catalog_chunk_text = (
            "[Product Catalog Match] Name: One Piece Luffy Gear 5 King of "
            "the Artist Special Version | Price: JPY 4,200.00 | "
            "Stock: 1 available | Description: Premium figurine"
        )
        retrieved = [ScoredChunk(id="product:1", text=catalog_chunk_text, score=1.0)]
        answer = (
            "Confirmed [1]! The One Piece Luffy Gear 5 King of the Artist "
            "Special Version is available — would you like a checkout link "
            "so I can lock that in for you right now today?"
        )
        pipeline = default_pipeline()
        out = pipeline.validate(
            answer,
            retrieved=retrieved,
            query="yes please\n" + catalog_chunk_text,
            surface="messenger",
        )
        assert not out.blocked, (
            f"catalog threading should prevent block; failed={out.failed_names} "
            f"reasons={[r.reason for r in out.results if r.failed]}"
        )


@pytest.mark.unit
class TestOutboundRecoveryBypass:
    """Phase 40 — outbound_recovery surface bypasses citation and exact_match;
    entropy validator must still run."""

    # Persuasive copy with checkout URL — no RAG citations, would normally
    # trip both citation (no [n] markers against non-empty retrieved) and
    # exact_match (CTA vocabulary echoes query tokens).
    #
    # IMPORTANT: the answer must be > 40 words so the pre-existing short-turn
    # bypass (0 < query_words <= 8 AND 0 < answer_words <= 40) does NOT fire
    # before the Phase 40 outbound_recovery branch is reached.  The query is
    # deliberately kept as the sentinel "[outbound_recovery]" (1 word) to
    # mirror real production traffic; lengthening the answer alone is
    # sufficient to disable the short-turn bypass.
    _ANSWER = (
        "Hey! We noticed you left a Brix Signature Tee in your cart earlier today. "
        "We saved it for you because we know great finds like this do not last long. "
        "Complete your order now and we will make sure it ships out today: "
        "https://example.com/checkout/abc"
    )
    _QUERY = "[outbound_recovery]"

    def test_outbound_recovery_bypass_citation_exact_match(self) -> None:
        """citation and exact_match must be bypassed; entropy still runs."""
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=[],  # no RAG chunks — citation would block without bypass
            query=self._QUERY,
            surface="outbound_recovery",
        )

        # citation must be bypassed
        citation_r = next(r for r in out.results if r.name == "citation")
        assert citation_r.passed, (
            f"citation must be bypassed for outbound_recovery; reason={citation_r.reason}"
        )
        assert citation_r.reason == "outbound_recovery_bypass"
        assert citation_r.metadata.get("bypassed") is True

        # exact_match must be bypassed
        exact_r = next(r for r in out.results if r.name == "exact_match")
        assert exact_r.passed, (
            f"exact_match must be bypassed for outbound_recovery; reason={exact_r.reason}"
        )
        assert exact_r.reason == "outbound_recovery_bypass"
        assert exact_r.metadata.get("bypassed") is True

        # entropy validator must NOT be bypassed (it ran normally)
        entropy_r = next(r for r in out.results if r.name == "entropy")
        assert entropy_r.metadata.get("bypassed") is not True, (
            "entropy must NOT be bypassed for outbound_recovery"
        )

    def test_non_recovery_surface_still_blocked_without_citation(self) -> None:
        """Confirm bypass is surface-gated: spa surface is still blocked on
        the same answer with no retrieved chunks (citation validator fires)."""
        pipeline = default_pipeline()
        out = pipeline.validate(
            self._ANSWER,
            retrieved=[],
            query=self._QUERY,
            surface="spa",
        )
        assert out.blocked, "spa surface must NOT receive the outbound_recovery bypass"
        assert "citation" in out.failed_names
