"""Human-handover signaling.

When the guardrails pipeline blocks a response (or the uncertainty score
exceeds the safe ceiling), we:

    1. Replace the answer with a deterministic, polite fallback string
       drawn from ``rag.guardrails.groundedness.abstention_text``.
    2. Mark the state with ``requires_human_handover=True`` so the
       Messenger sender / surface adapter can flag the thread for a human
       agent (Phase 8 will hook this to a Make/n8n outbound webhook).
    3. Record a structured log entry + Langfuse trace tag for ops review.

This module isolates that signalling so the orchestrator nodes stay
declarative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rag.guardrails.groundedness import abstention_text
from rag.observability.tracing import get_langfuse

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HandoverSignal:
    """Structured payload describing why a turn requires a human."""

    correlation_id: str
    thread_key: str
    surface: str
    reason: str
    validators_failed: tuple[str, ...]
    uncertainty_score: float
    retrieved_count: int
    answer_blocked: bool
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "thread_key": self.thread_key,
            "surface": self.surface,
            "reason": self.reason,
            "validators_failed": list(self.validators_failed),
            "uncertainty_score": self.uncertainty_score,
            "retrieved_count": self.retrieved_count,
            "answer_blocked": self.answer_blocked,
            "timestamp": self.timestamp,
        }


def emit_handover_signal(signal: HandoverSignal) -> None:
    """Structured log + Langfuse trace tag.

    Side-effects are best-effort — failures here must not break the
    response path. Future phases will additionally POST to
    ``MAKE_WEBHOOK_URL`` for CRM lead capture.
    """

    payload = signal.as_dict()
    _log.warning("handover_required %s", payload, extra={"handover": payload})

    langfuse = get_langfuse()
    if langfuse is None:
        return
    try:
        langfuse.event(
            name="chat.handover_required",
            level="WARNING",
            input=payload,
            metadata={"validators_failed": list(signal.validators_failed)},
        )
    except Exception as exc:  # pragma: no cover - defensive
        _log.debug("langfuse handover emit failed: %s", exc)


def handover_fallback_text() -> str:
    """The single deterministic message we send when handover is triggered."""

    return abstention_text()
