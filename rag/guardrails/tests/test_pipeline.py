"""Phase 5 GuardrailsPipeline tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from rag.guardrails.pipeline import (
    GuardrailsPipeline,
    PipelineResult,
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

    def validate(self, answer: str, *, retrieved):
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
        assert not out.blocked, f"failures: {[r.reason for r in out.results if r.failed]}"

    def test_fabricated_price_blocks(self) -> None:
        pipeline = default_pipeline()
        retrieved = [ScoredChunk(id="a", text="our plan starts at $99", score=1.0)]
        answer = "Plan starts at $147.99 [1]."
        out = pipeline.validate(answer, retrieved=retrieved)
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
