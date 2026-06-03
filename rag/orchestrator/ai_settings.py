"""Phase 45 — Lifecycle Persona Engine: ai_settings helpers.

Single source of truth for the ai_settings blob shape, merge logic, DB loader,
and prompt assembly.  All functions are pure or async-pure — no global mutable
state, no silent excepts, no event-loop blocking.

Public surface
--------------
DEFAULT_AI_SETTINGS     : dict  — the canonical empty-default blob.
merged_ai_settings      : (raw) -> dict  — deep-merge raw over default; never KeyErrors.
load_ai_settings        : async (slug, db) -> dict  — DB read + merge; never raises.
assemble_system_prompt  : (base, ai_settings, state) -> str  — Phase 45 suffix.

Phase 47 / Phase 48 stubs (harmless, wired in their own phases):
_node_enabled           : (state, key) -> bool  — default-True.
resolve_model_params    : (ai_settings) -> (model, temperature, max_tokens).
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.models import Tenant

if TYPE_CHECKING:
    from rag.orchestrator.state import NexusState

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical default blob
# ---------------------------------------------------------------------------

DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "version": 1,
    "scenario_prompts": {
        "introduction": "",  # first-turn opener overlay
        "core_behavior": "",  # ALWAYS appended persona/policy when non-empty
        "checkout_transition": "",  # buy-intent overlay
        "human_handoff": "",  # HITL overlay
    },
    "active_nodes": {  # Phase 47 — all default True (= current behavior)
        "sentiment_analysis": True,
        "research_mode": True,  # gates plan_research path via route_decision
        "inject_product_context": True,
        "build_carousel": True,
        "sdr_persona": True,  # gates SDR tools + persona overlay
        "hitl_handover": True,  # gates guardrails handover emission
    },
    "model_params": {  # Phase 48 — None => settings.* fallback
        "temperature": None,
        "max_tokens": None,
        "model_choice": None,
    },
}


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------


def merged_ai_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge *raw* over DEFAULT_AI_SETTINGS.

    Returns a fully-populated dict — every key present with a correct type so
    downstream nodes never need defensive ``.get`` chains.

    Rules
    -----
    * ``None`` raw → return a fresh copy of the default.
    * Top-level keys missing from *raw* are filled from the default.
    * Sub-dict values are merged key-by-key (one level deep); unknown sub-keys
      in *raw* are preserved so forward-compatible blobs round-trip cleanly.
    * Never raises, never mutates the default.
    """
    if not raw:
        return copy.deepcopy(DEFAULT_AI_SETTINGS)

    result: dict[str, Any] = copy.deepcopy(DEFAULT_AI_SETTINGS)
    for key, default_val in DEFAULT_AI_SETTINGS.items():
        if key not in raw:
            continue
        incoming = raw[key]
        if isinstance(default_val, dict) and isinstance(incoming, dict):
            # Shallow sub-dict merge: default sub-keys first, then incoming.
            merged_sub = dict(default_val)
            merged_sub.update(incoming)
            result[key] = merged_sub
        else:
            result[key] = incoming
    return result


# ---------------------------------------------------------------------------
# DB loader
# ---------------------------------------------------------------------------


async def load_ai_settings(
    tenant_slug: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Load and merge ``ai_settings`` for *tenant_slug* from the database.

    Returns ``merged_ai_settings(None)`` (the full default) when:
    * The tenant row is not found (e.g. a stale slug in flight).
    * Any exception is raised (connection error, etc.) — logs at WARNING.

    Never raises.  Callers should treat the return value as authoritative even
    in degraded mode because the default preserves current behavior exactly.
    """
    try:
        row = await db.scalar(
            select(Tenant.ai_settings).where(Tenant.slug == tenant_slug)
        )
        return merged_ai_settings(row)
    except Exception:
        _log.warning(
            "load_ai_settings: failed to load settings for tenant=%r; "
            "falling back to defaults",
            tenant_slug,
            exc_info=True,
        )
        return merged_ai_settings(None)


# ---------------------------------------------------------------------------
# Prompt assembly — Phase 45.3
# ---------------------------------------------------------------------------


def _is_first_turn(state: "NexusState") -> bool:
    """Return True when the conversation has no prior history."""
    return not bool(state.get("history"))


def _is_buy_intent(state: "NexusState") -> bool:
    """Return True when the inject-product-context node populated products."""
    return bool(state.get("_enriched_products"))


def assemble_system_prompt(
    base: str,
    ai_settings: dict[str, Any],
    state: "NexusState",
) -> str:
    """Return the Phase 45 persona suffix to append after the base prompt.

    The suffix is ONLY the extra content (core_behavior + one situational).
    It is empty when ai_settings carries all-default (empty-string) values,
    preserving byte-identical behavior for tenants who have not configured
    Prompt Studio.

    Suffix construction
    -------------------
    1. ``core_behavior`` — always appended when non-empty.
    2. Exactly ONE situational overlay (first match wins; empty entries skipped):
       a. ``human_handoff``       if state has ``requires_human_handover`` truthy.
       b. ``checkout_transition`` if _is_buy_intent(state).
       c. ``introduction``        if _is_first_turn(state).

    Returns an empty string when nothing applies (the common case for default
    tenants).
    """
    prompts: dict[str, str] = ai_settings.get("scenario_prompts") or {}

    core_behavior = (prompts.get("core_behavior") or "").strip()

    # Situational: exactly one, priority order.
    situational = ""
    if state.get("requires_human_handover"):
        situational = (prompts.get("human_handoff") or "").strip()
    elif _is_buy_intent(state):
        situational = (prompts.get("checkout_transition") or "").strip()
    elif _is_first_turn(state):
        situational = (prompts.get("introduction") or "").strip()

    parts: list[str] = []
    if core_behavior:
        parts.append(core_behavior)
    if situational:
        parts.append(situational)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 47 stub — node toggle helper
# ---------------------------------------------------------------------------


def _node_enabled(state: "NexusState", key: str) -> bool:
    """Return whether *key* is enabled in the tenant's active_nodes map.

    Defaults to True so callers behave identically to pre-Phase-47 when the
    state carries the default blob (all nodes enabled).  Phase 47 wires this
    into individual node guards.
    """
    ai: dict[str, Any] = state.get("ai_settings") or {}
    active_nodes: dict[str, Any] = ai.get("active_nodes") or {}
    val = active_nodes.get(key)
    # Explicit False disables; anything else (True, missing) enables.
    return val is not False


# ---------------------------------------------------------------------------
# Phase 48 stub — model param resolver
# ---------------------------------------------------------------------------


def resolve_model_params(
    ai_settings: dict[str, Any],
) -> tuple[str, float, int]:
    """Resolve (model, temperature, max_tokens) with settings.* fallback.

    Phase 48 wires this into generate_node text path.  Until then it is
    callable but not invoked from any hot path.

    Bounds mirror rag/config.py: temp 0-2, max_tokens 64-8192.
    model_choice must be in _MODEL_ALLOWLIST or settings fallback is used.
    """
    from rag.config import settings  # noqa: PLC0415  (lazy — avoids circular import)

    _MODEL_ALLOWLIST = {
        settings.generation_model,
        settings.vision_model,
        settings.followup_model,
    }

    mp: dict[str, Any] = (ai_settings or {}).get("model_params") or {}

    t = mp.get("temperature")
    temperature = (
        float(t)
        if isinstance(t, (int, float)) and 0.0 <= t <= 2.0
        else settings.generation_temperature
    )

    m = mp.get("max_tokens")
    max_tokens = (
        int(m)
        if isinstance(m, int) and 64 <= m <= 8192
        else settings.generation_max_tokens
    )

    c = mp.get("model_choice")
    model = (
        str(c)
        if isinstance(c, str) and c in _MODEL_ALLOWLIST
        else settings.generation_model
    )

    return model, temperature, max_tokens
