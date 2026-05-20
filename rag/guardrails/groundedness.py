"""Structural groundedness validator.

Phase 3 ships an in-house validator that enforces the citation discipline
the surface system prompts mandate:

    1. Every factual claim carries a ``[n]`` citation marker.
    2. Every ``[n]`` resolves to a chunk in the retrieved context.
    3. If the retrieved context is empty, the answer must be an abstention.

This is a *structural* check, not a deep semantic groundedness check.
Phase 7 will additionally wire Guardrails AI's ``provenance_v1`` validator
(LLM-as-judge over each sentence) for the semantic layer. Until then this
catches the most common hallucination shapes — fabricated citation indices
and ungrounded claims with no citations at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.retrieval.types import ScoredChunk

_CITATION_RE = re.compile(r"\[(\d+)\]")

_ABSTENTION_MARKERS: tuple[str, ...] = (
    "i don't have",
    "do not have",
    "cannot confirm",
    "not in our knowledge",
    "vault doesn't cover",
    "not enough information",
    "route to a human",
    "route you to",
    "connect you with our team",
)


@dataclass(frozen=True)
class GroundednessResult:
    passed: bool
    reason: str | None
    cited_ids: tuple[str, ...]

    @property
    def failed(self) -> bool:
        return not self.passed


def _is_abstention(answer: str) -> bool:
    lowered = answer.lower()
    return any(marker in lowered for marker in _ABSTENTION_MARKERS)


def check_groundedness(
    answer: str,
    retrieved: list[ScoredChunk],
) -> GroundednessResult:
    """Return a :class:`GroundednessResult` describing whether ``answer`` is
    safe to emit given ``retrieved`` context.

    Pass conditions:
        - retrieved is empty AND answer is an honest abstention, or
        - retrieved is non-empty AND every [n] in answer resolves to a chunk
          AND at least one citation is present (so the answer is anchored).
    """

    answer = (answer or "").strip()
    if not answer:
        return GroundednessResult(False, "empty answer", ())

    cited_indices = sorted({int(m.group(1)) for m in _CITATION_RE.finditer(answer)})

    if not retrieved:
        if _is_abstention(answer):
            return GroundednessResult(True, "honest abstention; no context", ())
        return GroundednessResult(
            False, "no retrieved context but answer asserts content", ()
        )

    if not cited_indices:
        if _is_abstention(answer):
            return GroundednessResult(True, "honest abstention", ())
        return GroundednessResult(
            False, "factual claims emitted without citations", ()
        )

    max_valid = len(retrieved)
    out_of_range = [idx for idx in cited_indices if idx < 1 or idx > max_valid]
    if out_of_range:
        return GroundednessResult(
            False,
            f"citation indices {out_of_range} exceed retrieved set ({max_valid})",
            (),
        )

    cited_ids = tuple(retrieved[idx - 1].id for idx in cited_indices)
    return GroundednessResult(True, None, cited_ids)


def abstention_text() -> str:
    """The single deterministic fallback we emit when guardrails fail."""

    return (
        "I don't have confident information on that in our knowledge base. "
        "Reply with a few more details and I'll route you to a human agent on our team."
    )
