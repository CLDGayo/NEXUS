"""Uncertainty / "semantic entropy" gate.

Phase 5 ships the **lightweight proxy** (single LLM call, free): a score
in ``[0, 1]`` derived from lexical hedging markers, citation density, and
answer-length sanity. Higher score = lower confidence; above
``UNCERTAINTY_CEILING`` the validator fails and the pipeline routes to
the deterministic fallback.

True semantic entropy (Farquhar et al. 2024) requires N additional model
samples + a small embedder for semantic-equivalence clustering. That's
expensive and is deliberately deferred behind a flag — see
``compute_semantic_entropy`` for the hook.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rag.guardrails.validators import ValidationResult
from rag.retrieval.types import ScoredChunk

# Words that signal speaker uncertainty. Token-boundary matched.
_HEDGE_PATTERNS: tuple[str, ...] = (
    r"\bmight\b", r"\bmay\b", r"\bcould\b", r"\bpossibly\b", r"\bperhaps\b",
    r"\bmaybe\b", r"\bi think\b", r"\bi believe\b", r"\bnot sure\b",
    r"\bunclear\b", r"\bunknown\b", r"\bapproximate(?:ly)?\b",
    r"\baround\b", r"\broughly\b", r"\bsomewhere\b", r"\bsome(?:what|kind)\b",
    r"\bit seems\b", r"\bappears to\b",
)
_HEDGE_RE = re.compile("|".join(_HEDGE_PATTERNS), re.IGNORECASE)

_CITATION_RE = re.compile(r"\[\d+\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Tuned so a fully grounded, citation-dense answer scores ~0.1 and a
# heavily hedged uncited answer scores ~0.9.
_HEDGE_WEIGHT = 0.4
_CITATION_WEIGHT = 0.45
_LENGTH_WEIGHT = 0.15

# Empirical floor for "too short to mean anything"; below this we treat
# answer as low-confidence regardless of phrasing.
_MIN_INFORMATIVE_WORDS = 6


def _count_hedges(text: str) -> int:
    return len(_HEDGE_RE.findall(text))


def _citation_density(text: str) -> float:
    """Citations per declarative sentence."""

    sentences = [s for s in _SENTENCE_RE.split(text) if s.strip()]
    if not sentences:
        return 0.0
    citations = len(_CITATION_RE.findall(text))
    return citations / len(sentences)


def compute_uncertainty_score(
    answer: str, retrieved: list[ScoredChunk]
) -> float:
    """Single-pass uncertainty proxy in ``[0, 1]``. Higher = less confident.

    Three weighted components:
        * Hedge frequency (more hedges → higher score, saturates at 5 hedges)
        * Citation deficit (fewer citations per sentence → higher score)
        * Length floor (very short answers → high score)
    """

    answer = (answer or "").strip()
    if not answer:
        return 1.0

    hedge_count = _count_hedges(answer)
    hedge_score = min(hedge_count / 5.0, 1.0)

    citation_density = _citation_density(answer)
    # Density of 1.0 = perfect coverage (every sentence cited). Linear
    # falloff to 0 below that.
    citation_deficit = max(0.0, 1.0 - min(citation_density, 1.0))
    # If there is no retrieved context, citation density can't help.
    if not retrieved:
        citation_deficit = 0.0

    word_count = len(answer.split())
    length_score = (
        1.0 if word_count < _MIN_INFORMATIVE_WORDS
        else 1.0 - min(word_count / 50.0, 1.0)
    )

    raw = (
        hedge_score * _HEDGE_WEIGHT
        + citation_deficit * _CITATION_WEIGHT
        + length_score * _LENGTH_WEIGHT
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Heavy mode (opt-in, Phase 9+) — semantic entropy via N-sample clustering
# ---------------------------------------------------------------------------

def compute_semantic_entropy(
    samples: list[str],
    *,
    cluster_threshold: float = 0.85,
    embedder=None,
) -> float:
    """Cluster-based Shannon entropy over semantically equivalent answers.

    Pseudocode (real implementation requires an embedder):
        1. Embed each sample.
        2. Cluster by cosine similarity ≥ ``cluster_threshold``.
        3. p_i = |cluster_i| / N.
        4. Return -Σ p_i log(p_i) / log(N).

    Not wired into the default pipeline because it costs N additional LLM
    calls per turn. Enable when latency budget allows (Phase 9+).
    """

    if not samples:
        return 1.0
    if embedder is None:  # pragma: no cover - hook for opt-in path
        # Fallback: treat each distinct string as its own cluster — strict.
        unique = len(set(samples))
        if unique <= 1:
            return 0.0
        p = 1.0 / unique
        return -unique * p * math.log(p) / math.log(len(samples))
    raise NotImplementedError(
        "embedder-backed semantic entropy is Phase 9+; see docstring"
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

@dataclass
class EntropyValidator:
    """Fails when the answer's uncertainty score exceeds the ceiling."""

    name: str = "entropy"
    ceiling: float = 0.7

    def validate(
        self, answer: str, *, retrieved: list[ScoredChunk]
    ) -> ValidationResult:
        score = compute_uncertainty_score(answer, retrieved)
        passed = score <= self.ceiling
        return ValidationResult(
            name=self.name,
            passed=passed,
            reason=(
                None if passed else
                f"uncertainty score {score:.2f} exceeds ceiling {self.ceiling:.2f}"
            ),
            severity="critical" if score > self.ceiling + 0.15 else "warning",
            metadata={"score": score, "ceiling": self.ceiling},
        )
