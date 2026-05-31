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
        surface: str = "",
        has_attachments: bool = False,
    ) -> PipelineResult:
        results: list[ValidationResult] = []
        # Phase 33.1 — Messenger SDR persona generates conversational CTAs
        # ("Would you like me to check stock?") that bleed common verbs
        # and franchise nouns from the user's query. Bump the exact-match
        # tolerance for the Messenger surface only; SPA stays strict.
        _SDR_MAX_SUSPICIOUS = 5
        # Short conversational turns ("hi", "I am clarence", "who am I?")
        # with terse replies can't carry P0 hallucinations worth scanning
        # for exact-match or strict citation. Bypass both so a self-
        # introduction or greeting doesn't get blocked by either (the
        # ExactMatchValidator still backstops factual fabrication on
        # longer turns; EntropyValidator still gates wishy-washy text).
        is_short_turn = 0 < len(query.split()) <= 8 and 0 < len(answer.split()) <= 40
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
                        {int(m.group(1)) for m in _CITATION_MARKER_RE.finditer(answer)}
                    )
                    valid_ids = [
                        retrieved[i - 1].id for i in indices if 1 <= i <= len(retrieved)
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
            # Phase 33.2 — Messenger vision path bypasses ``citation``.
            # The vision model hallucinates out-of-bounds [n] indices
            # (e.g. [11] against a 4-chunk context) because it's weaker
            # at structural formatting than text-only models. Grounding
            # for the vision path comes from the image itself plus the
            # ``product_branch`` catalog injection, not from RAG ``[n]``
            # indices, so dropping citation here doesn't relax factual
            # safety in any meaningful way. ``exact_match`` and
            # ``entropy`` still run on this path.
            if surface == "messenger" and has_attachments and v_name == "citation":
                # Still surface any valid [n] markers so downstream
                # surface adapters (Messenger sender) can render source
                # tags. Mirrors the short-turn bypass logic above —
                # out-of-bounds indices are silently dropped here, which
                # is the whole point of the bypass.
                indices = sorted(
                    {int(m.group(1)) for m in _CITATION_MARKER_RE.finditer(answer)}
                )
                valid_ids = [
                    retrieved[i - 1].id for i in indices if 1 <= i <= len(retrieved)
                ]
                results.append(
                    ValidationResult(
                        name=v_name,
                        passed=True,
                        reason="vision-path bypass",
                        metadata={"bypassed": True, "cited_ids": valid_ids},
                    )
                )
                continue
            # Phase 33.1 — surface-aware threshold bump. The
            # ExactMatchValidator's instance ``max_suspicious`` is mutated
            # for the duration of this single call only; ``try/finally``
            # guarantees the original value is restored even if the
            # validator raises, so the module-level pipeline singleton
            # can never leak the bumped threshold across requests.
            saved_max_suspicious: int | None = None
            if (
                surface == "messenger"
                and v_name == "exact_match"
                and hasattr(validator, "max_suspicious")
            ):
                saved_max_suspicious = validator.max_suspicious  # type: ignore[attr-defined]
                validator.max_suspicious = _SDR_MAX_SUSPICIOUS  # type: ignore[attr-defined]
            try:
                result = validator.validate(answer, retrieved=retrieved, query=query)
            except Exception as exc:
                # A validator that crashes is treated as a critical fail —
                # never silently pass an answer when the safety layer broke.
                result = ValidationResult(
                    name=getattr(validator, "name", validator.__class__.__name__),
                    passed=False,
                    reason=f"validator raised: {exc}",
                    severity="critical",
                )
            finally:
                if saved_max_suspicious is not None:
                    validator.max_suspicious = saved_max_suspicious  # type: ignore[attr-defined]
            results.append(result)

        critical_failures = [
            r for r in results if r.failed and r.severity == "critical"
        ]
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
