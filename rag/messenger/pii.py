"""PII scrubbing for inbound user messages.

Runs in the webhook hot path BEFORE the graph runner and BEFORE any
Langfuse/OTEL span captures the request body. Replaces six common PII
categories with deterministic redaction tokens so downstream LLM prompts,
trace stores, and dashboards never see raw values.

Pure module — no I/O, no logging, no global state. Six precompiled
regexes plus an inline Luhn check on credit-card candidates to suppress
false positives on long order numbers or invoice IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

PiiKind = Literal["EMAIL", "IBAN", "CARD", "SSN", "IP", "PHONE"]

REPLACEMENTS: dict[PiiKind, str] = {
    "EMAIL": "[EMAIL_REDACTED]",
    "IBAN": "[IBAN_REDACTED]",
    "CARD": "[CARD_REDACTED]",
    "SSN": "[SSN_REDACTED]",
    "IP": "[IP_REDACTED]",
    "PHONE": "[PHONE_REDACTED]",
}


@dataclass(frozen=True)
class Redaction:
    kind: PiiKind
    span: tuple[int, int]


@dataclass(frozen=True)
class ScrubResult:
    scrubbed_text: str
    redactions: tuple[Redaction, ...]

    @property
    def counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.redactions:
            out[r.kind] = out.get(r.kind, 0) + 1
        return out


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# IBAN: 2 letters + 2 digits + 11–30 alphanumerics (per ISO 13616).
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# CC candidate: 13–19 total digits, optionally separated by spaces or dashes.
_CC_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Dotted-quad IPv4; each octet validated post-match.
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Phone: optional +country, then 7–15 digits with allowed separators.
# Lookarounds prevent matching inside a longer alphanumeric token.
_PHONE_RE = re.compile(r"(?<![\w\d])\+?\d[\d\s().\-]{5,18}\d(?![\w\d])")


def _luhn_valid(digits: str) -> bool:
    """Standard Luhn checksum over a pure-digit string."""

    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _collect_spans(text: str) -> list[tuple[int, int, PiiKind]]:
    spans: list[tuple[int, int, PiiKind]] = []

    for m in _EMAIL_RE.finditer(text):
        spans.append((m.start(), m.end(), "EMAIL"))

    for m in _IBAN_RE.finditer(text):
        spans.append((m.start(), m.end(), "IBAN"))

    for m in _CC_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ \-]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            spans.append((m.start(), m.end(), "CARD"))

    for m in _SSN_RE.finditer(text):
        spans.append((m.start(), m.end(), "SSN"))

    for m in _IP_RE.finditer(text):
        try:
            octets = [int(p) for p in m.group().split(".")]
        except ValueError:
            continue
        if len(octets) == 4 and all(0 <= o <= 255 for o in octets):
            spans.append((m.start(), m.end(), "IP"))

    for m in _PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 7 <= len(digits) <= 15:
            spans.append((m.start(), m.end(), "PHONE"))

    return spans


def _dedup_spans(
    spans: list[tuple[int, int, PiiKind]],
) -> list[tuple[int, int, PiiKind]]:
    """Resolve overlaps. Earliest start wins; ties broken by longest match."""

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out: list[tuple[int, int, PiiKind]] = []
    end_so_far = -1
    for start, end, kind in spans:
        if start >= end_so_far:
            out.append((start, end, kind))
            end_so_far = end
    return out


def scrub(text: str) -> ScrubResult:
    """Replace detected PII spans with their canonical redaction tokens."""

    if not text:
        return ScrubResult(scrubbed_text=text, redactions=())

    filtered = _dedup_spans(_collect_spans(text))
    if not filtered:
        return ScrubResult(scrubbed_text=text, redactions=())

    parts: list[str] = []
    redactions: list[Redaction] = []
    cursor = 0
    for start, end, kind in filtered:
        parts.append(text[cursor:start])
        parts.append(REPLACEMENTS[kind])
        redactions.append(Redaction(kind=kind, span=(start, end)))
        cursor = end
    parts.append(text[cursor:])
    return ScrubResult(scrubbed_text="".join(parts), redactions=tuple(redactions))
