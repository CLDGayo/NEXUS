"""Phase 5 validator suite.

Three structural validators run before the LLM output reaches the wire:

    * ``CitationValidator``  — wraps the Phase 3 groundedness check
                               (every factual claim must carry [n]).
    * ``ExactMatchValidator`` — catches fabricated specifics (prices,
                                dates, proper nouns) by verifying every
                                digit-group and capitalized noun appears
                                verbatim in the retrieved chunks.
    * ``EntropyValidator``    — single-pass lexical uncertainty proxy
                                (hedging markers, low citation density).

All validators expose the same protocol:

    result = validator.validate(answer, retrieved=[…])
    # ValidationResult(passed, name, reason, severity, metadata)

The pipeline (``rag.guardrails.pipeline.GuardrailsPipeline``) chains them
together so the orchestrator's ``guardrails_node`` calls a single entry
point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from rag.guardrails.groundedness import check_groundedness
from rag.retrieval.types import ScoredChunk

Severity = Literal["critical", "warning"]


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of one validator run."""

    name: str
    passed: bool
    reason: str | None = None
    severity: Severity = "critical"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.passed


class Validator(Protocol):
    """Structural type for any validator. Pipeline iterates this.

    Extra keyword arguments (``query``, future per-turn context) are passed
    through; validators that don't consume them should accept ``**kwargs``
    and ignore.
    """

    name: str

    def validate(
        self, answer: str, *, retrieved: list[ScoredChunk], **kwargs: Any
    ) -> ValidationResult: ...


# ---------------------------------------------------------------------------
# Citation validator (Phase 3 groundedness wrapped)
# ---------------------------------------------------------------------------


@dataclass
class CitationValidator:
    name: str = "citation"

    def validate(
        self, answer: str, *, retrieved: list[ScoredChunk], **_kwargs: Any
    ) -> ValidationResult:
        result = check_groundedness(answer, retrieved)
        return ValidationResult(
            name=self.name,
            passed=result.passed,
            reason=result.reason,
            metadata={"cited_ids": list(result.cited_ids)},
        )


# ---------------------------------------------------------------------------
# Exact-match validator
# ---------------------------------------------------------------------------

# Strip `[n]` citation markers before exact-match scanning so the validator
# doesn't flag "1" as a fabricated number when it's part of "[1]".
_CITATION_MARKER_RE = re.compile(r"\[\d+\]")
# Digit groups (prices, ids, dates, percentages).
_DIGIT_RE = re.compile(
    r"\$?\d[\d,]*\.?\d*%?|\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}|\d{2}/\d{2}/\d{2,4}"
)
# Capitalized words excluding very common starts/stopwords.
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Words that look "proper" syntactically but aren't claims worth verifying.
_PROPER_NOUN_ALLOWLIST: frozenset[str] = frozenset(
    word.lower()
    for word in (
        "I",
        "We",
        "Our",
        "Your",
        "Their",
        "His",
        "Her",
        "My",
        "You",
        "The",
        "This",
        "That",
        "These",
        "Those",
        "There",
        "Here",
        "When",
        "Where",
        "Why",
        "How",
        "What",
        "Who",
        "Which",
        "Hi",
        "Hey",
        "Hello",
        "Thanks",
        "Thank",
        "Please",
        "Yes",
        "No",
        "Okay",
        "OK",
        "Reply",
        "Send",
        "Tap",
        "Click",
        "Call",
        "Email",
        "Message",
        "Chat",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        "AM",
        "PM",
        "USD",
        "EUR",
        "GBP",
        "PHP",
        # Owner identity (vault subject). The bot may say these in any turn
        # — they're stage props, not claims to verify.
        "Clarence",
        "Nexus",
        "Gayo",
        "Sphere",
        # Phase 33.1 — SDR conversational filler. The Messenger persona
        # overlay instructs the LLM to end every reply with a CTA
        # ("Would you like me to check stock?", "Shall I send a link?").
        # These verbs/adjectives are not factual claims and were causing
        # exact_match false positives on legitimate sales responses.
        "Would",
        "Could",
        "Shall",
        "Should",
        "Let",
        "Just",
        "Also",
        "Sure",
        "Great",
        "Absolutely",
        "Definitely",
        "Happy",
        "Like",
        "Want",
        "Need",
        "Check",
        "Look",
        "Help",
    )
)


def _normalize_numeric(token: str) -> str:
    return token.lstrip("$").rstrip("%").replace(",", "")


def _retrieved_text_blob(
    retrieved: list[ScoredChunk], *, extra: str = ""
) -> tuple[str, str]:
    """Return (lowercased blob, normalized digits-only blob) over context.

    The blob includes both each chunk's text **and** string-valued metadata
    fields (title, aliases, tags, folder, heading_path). Metadata is real
    context per CLAUDE.md §1 Stage 2 — names that live only in frontmatter
    (an alias, a tag) shouldn't get flagged as fabricated.

    ``extra`` lets the pipeline thread the user query into the blob so a
    user introducing themselves ("I am Clarence") makes their own name
    non-suspicious in the same turn.
    """

    parts: list[str] = []
    for c in retrieved:
        if c.text:
            parts.append(c.text)
        for value in c.metadata.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (list, tuple)):
                parts.extend(item for item in value if isinstance(item, str))
    if extra:
        parts.append(extra)
    joined = "\n".join(parts)
    return joined.lower(), joined.replace(",", "").lower()


@dataclass
class ExactMatchValidator:
    """Flags digit groups + proper nouns in the answer that do not appear
    verbatim in any retrieved chunk.

    Catches the highest-cost hallucinations a public-facing bot makes:
    fabricated prices, dates, customer/partner names, and time slots.
    Whole-word matching for nouns; comma-insensitive matching for digits.
    """

    name: str = "exact_match"
    # Tolerate up to 2 unverifiable proper nouns / numerics before blocking.
    # ``0`` was the right call for a public-facing booking bot; on a personal
    # second-brain surface where the user is the subject, a single sibling
    # entity bleeding in shouldn't nuke the whole answer. High-stakes
    # pipelines can still set this back to 0.
    max_suspicious: int = 2

    def validate(
        self,
        answer: str,
        *,
        retrieved: list[ScoredChunk],
        query: str = "",
        **_kwargs: Any,
    ) -> ValidationResult:
        if not answer.strip():
            return ValidationResult(name=self.name, passed=False, reason="empty answer")
        if not retrieved:
            # No context to compare against → defer to CitationValidator's
            # abstention path; don't double-fail here.
            return ValidationResult(
                name=self.name, passed=True, reason="no retrieved context to verify"
            )

        joined_lower, digits_blob = _retrieved_text_blob(retrieved, extra=query)

        # Citation markers like ``[1]`` are bookkeeping, not factual claims.
        # Drop them before scanning for fabricated numerics/nouns.
        scan_target = _CITATION_MARKER_RE.sub("", answer)

        suspicious: list[dict[str, str]] = []

        for match in _DIGIT_RE.finditer(scan_target):
            token = match.group()
            normalized = _normalize_numeric(token)
            if not normalized:
                continue
            if normalized.lower() in joined_lower:
                continue
            if normalized.lower() in digits_blob:
                continue
            suspicious.append({"kind": "numeric", "token": token})

        sentences = _SENTENCE_RE.split(scan_target)
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            words = stripped.split()
            # Split each token on non-word chars so "Retrieval-Augmented"
            # becomes ["Retrieval","Augmented"] and "I'll" becomes ["I","ll"].
            # Otherwise hyphenated compounds and contractions get falsely
            # flagged because their concatenated form ("RetrievalAugmented",
            # "Ill") never appears in retrieved context.
            for word in words[1:]:  # skip sentence-initial cap (always cap)
                for bare in re.split(r"\W+", word):
                    if not bare or not _PROPER_RE.fullmatch(bare):
                        continue
                    if bare.lower() in _PROPER_NOUN_ALLOWLIST:
                        continue
                    if bare.lower() in joined_lower:
                        continue
                    suspicious.append({"kind": "proper_noun", "token": bare})

        if len(suspicious) > self.max_suspicious:
            tokens_summary = ", ".join(s["token"] for s in suspicious[:6])
            return ValidationResult(
                name=self.name,
                passed=False,
                reason=(
                    f"{len(suspicious)} suspicious token(s) not in retrieved context: "
                    f"{tokens_summary}"
                ),
                metadata={"suspicious": suspicious},
            )

        return ValidationResult(name=self.name, passed=True, metadata={"checked": True})
