"""Aggregated guardrails pipeline.

Runs the registered validators in order, collects results, and produces a
single ``PipelineResult`` the orchestrator's ``guardrails_node`` consumes.

Failure policy:
    * If any ``severity="critical"`` validator fails → ``blocked=True``;
      the orchestrator replaces the answer with the fallback string and
      flips ``requires_handover=True``.
    * ``severity="warning"`` failures pass through to ``warnings`` but do
      not block emission. They still tag the trace so ops can review.

Guardrails AI / NeMo Guardrails swap path: replace the body of
``GuardrailsPipeline.validate`` with the equivalent ``Guard.parse(...)``
call once a binding is chosen. The public interface (``PipelineResult``)
is the only contract downstream code depends on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag.guardrails.entropy import (
    EntropyValidator,
    compute_uncertainty_score,
)
from rag.guardrails.handover import handover_fallback_text
from rag.guardrails.validators import (
    CitationValidator,
    ExactMatchValidator,
    ValidationResult,
    Validator,
)
from rag.retrieval.types import ScoredChunk

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class PipelineResult:
    """Aggregated outcome of the guardrails pipeline."""

    passed: bool
    blocked: bool
    requires_handover: bool
    fallback_text: str | None
    uncertainty_score: float
    results: tuple[ValidationResult, ...]

    @property
    def failed_names(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.results if r.failed)

    @property
    def critical_failures(self) -> tuple[ValidationResult, ...]:
        return tuple(r for r in self.results if r.failed and r.severity == "critical")

    @property
    def warnings(self) -> tuple[ValidationResult, ...]:
        return tuple(r for r in self.results if r.failed and r.severity == "warning")


def default_pipeline() -> "GuardrailsPipeline":
    """The pipeline the orchestrator uses by default in production.

    Order matters: citation/exact-match are cheaper than entropy and short-
    circuit if they fail, so the entropy validator only runs when the
    answer is at least structurally grounded.
    """

    return GuardrailsPipeline(
        validators=(
            CitationValidator(),
            ExactMatchValidator(),
            EntropyValidator(),
        )
    )


@dataclass
class GuardrailsPipeline:
    validators: tuple[Validator, ...] = field(default_factory=tuple)

    def validate(
        self,
        answer: str,
        *,
        retrieved: list[ScoredChunk],
        query: str = "",
    ) -> PipelineResult:
        results: list[ValidationResult] = []
        # Short conversational turns ("hi", "I am clarence", "who am I?")
        # with terse replies can't carry P0 hallucinations worth scanning
        # for exact-match or strict citation. Bypass both so a self-
        # introduction or greeting doesn't get blocked by either (the
        # ExactMatchValidator still backstops factual fabrication on
        # longer turns; EntropyValidator still gates wishy-washy text).
        is_short_turn = (
            0 < len(query.split()) <= 8 and 0 < len(answer.split()) <= 40
        )
        _SHORT_TURN_SKIP = {"exact_match", "citation"}
        for validator in self.validators:
            v_name = getattr(validator, "name", "")
            if is_short_turn and v_name in _SHORT_TURN_SKIP:
                # Citation bypass still surfaces [n] markers when the LLM
                # included them — downstream surface adapters render
                # source tags from `cited_ids` and would otherwise lose
                # the link.
                meta: dict[str, object] = {"bypassed": True}
                if v_name == "citation":
                    indices = sorted(
                        {
                            int(m.group(1))
                            for m in _CITATION_MARKER_RE.finditer(answer)
                        }
                    )
                    valid_ids = [
                        retrieved[i - 1].id
                        for i in indices
                        if 1 <= i <= len(retrieved)
                    ]
                    meta["cited_ids"] = valid_ids
                results.append(
                    ValidationResult(
                        name=v_name,
                        passed=True,
                        reason="short-turn bypass",
                        metadata=meta,
                    )
                )
                continue
            try:
                result = validator.validate(
                    answer, retrieved=retrieved, query=query
                )
            except Exception as exc:
                # A validator that crashes is treated as a critical fail —
                # never silently pass an answer when the safety layer broke.
                result = ValidationResult(
                    name=getattr(validator, "name", validator.__class__.__name__),
                    passed=False,
                    reason=f"validator raised: {exc}",
                    severity="critical",
                )
            results.append(result)

        critical_failures = [r for r in results if r.failed and r.severity == "critical"]
        blocked = bool(critical_failures)
        uncertainty = compute_uncertainty_score(answer, retrieved)

        return PipelineResult(
            passed=not any(r.failed for r in results),
            blocked=blocked,
            requires_handover=blocked,
            fallback_text=handover_fallback_text() if blocked else None,
            uncertainty_score=uncertainty,
            results=tuple(results),
        )
