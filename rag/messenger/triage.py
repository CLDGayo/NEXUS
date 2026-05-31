"""Phase 38 — Stateless public comment triage engine.

Single-shot LLM call to classify public Facebook Page comments by intent
and produce routing instructions. Bypasses LangGraph entirely — no state,
no checkpointer, no memory. Designed for high-velocity, low-latency
comment processing.

The 8B model (``settings.followup_model``) is used for cost efficiency.
Temperature 0.1 keeps output deterministic. JSON mode enforces the
strict schema.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal, cast

from rag.config import settings
from rag.orchestrator.llm import LLMError, chat_complete

_log = logging.getLogger(__name__)

TriageAction = Literal["public_only", "public_and_private", "ignore"]

_SYSTEM_PROMPT = """\
You are a social media triage assistant for a business Facebook Page.
Classify the following public comment and produce a JSON response.

## Classification Rules

- **Product/Pricing Inquiry** → action: "public_and_private"
  - public_reply: Friendly acknowledgment (e.g., "Great question! We just sent you a DM with all the details 💬")
  - private_reply: Strong opening hook that initiates a sales conversation (e.g., "Hi! Thanks for your interest in [topic]. Let me help you find exactly what you need...")

- **Complaint/Support Request** → action: "public_and_private"
  - public_reply: Empathetic de-escalation (e.g., "We're sorry to hear that. We've sent you a private message to resolve this right away 🙏")
  - private_reply: Priority support transition (e.g., "Hi, we want to make this right for you. Could you share more details about what happened so we can help?")

- **Praise/Positive Feedback** → action: "public_only"
  - public_reply: Warm, brand-aligned gratitude (e.g., "Thank you so much! 🙌 We're thrilled you love it!")
  - private_reply: null

- **Spam/Random Tags/Irrelevant** → action: "ignore"
  - public_reply: null
  - private_reply: null

## Output Schema (strict JSON, no markdown fences)

{
  "action": "public_only" | "public_and_private" | "ignore",
  "public_reply": "text or null",
  "private_reply": "text or null"
}
"""


@dataclass(frozen=True)
class TriageResult:
    """Structured output from the triage LLM call."""

    action: TriageAction
    public_reply: str | None
    private_reply: str | None


async def triage_comment(comment_text: str) -> TriageResult:
    """Classify a public comment and return routing instructions.

    Returns ``TriageResult(action="ignore")`` on any LLM or parsing
    failure — the engine never crashes, never blocks.
    """

    _IGNORE = TriageResult(action="ignore", public_reply=None, private_reply=None)

    if not comment_text.strip():
        return _IGNORE

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": comment_text},
    ]

    try:
        result = await chat_complete(
            messages,
            model=settings.followup_model,
            temperature=0.1,
            max_tokens=256,
            timeout_seconds=10.0,
            extra={"response_format": {"type": "json_object"}},
        )
    except LLMError as exc:
        _log.warning("triage.llm_error err=%s", exc)
        return _IGNORE

    try:
        parsed = json.loads(result.content)
    except (json.JSONDecodeError, TypeError) as exc:
        _log.warning("triage.parse_error content=%s err=%s", result.content[:200], exc)
        return _IGNORE

    if not isinstance(parsed, dict):
        _log.warning("triage.bad_shape type=%s", type(parsed).__name__)
        return _IGNORE

    action = parsed.get("action")
    if action not in ("public_only", "public_and_private", "ignore"):
        _log.warning("triage.invalid_action action=%s", action)
        return _IGNORE

    public_reply = parsed.get("public_reply")
    private_reply = parsed.get("private_reply")

    # Normalize "null" strings and empty strings to None.
    if not public_reply or public_reply == "null":
        public_reply = None
    if not private_reply or private_reply == "null":
        private_reply = None

    # Safe: the membership check above constrained ``action`` to the
    # TriageAction literal at runtime; mypy can't narrow an ``Any`` from
    # ``dict.get`` through a tuple ``in`` test, so cast explicitly.
    return TriageResult(
        action=cast(TriageAction, action),
        public_reply=public_reply,
        private_reply=private_reply,
    )
