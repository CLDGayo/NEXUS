# Phases 47 & 48 — Workflow Toggles + Model Params

**Date:** 2026-06-04
**Owner:** Clarence Lloyd Gayo
**Program:** Tenant AI Customization Umbrella (Phases 45–48)
**Version:** Unreleased

## Context

Phases 47 and 48 are the final two **backend** phases of the Tenant AI Customization umbrella program. They consume the `NexusState["ai_settings"]` field and the `ai_settings.py` helpers shipped in Phase 45.

- **Phase 47 — Workflow Node Toggles:** let a tenant disable individual graph nodes via `ai_settings.active_nodes`. The graph is compiled once and cached (`get_graph`); per-tenant recompile is rejected. So a disabled node early-returns a no-op (`{}` or an explicit neutral) — the topology never changes, only node bodies short-circuit (same pattern as `direct_fanout_node`).
- **Phase 48 — Per-Tenant Model Params:** let a tenant tune generation `temperature` / `max_tokens` / `model_choice` via `ai_settings.model_params`, fail-safe with bounds + an allowlist.

**Safety invariant (unchanged):** `active_nodes.*` default `True`, `model_params.*` default `None`. A tenant who never opens Prompt Studio gets byte-identical behavior.

**Partial work found on resume:** the helpers were *already fully implemented* in `ai_settings.py` (not stubs) and `nodes.py` already imported both; the `sentiment_analysis` and `route_decision`/`research_mode` toggles were already wired. (A stale project memory claimed the helpers were stubbed — corrected.) So this session's scope was the four remaining Phase 47 guards + the Phase 48 `generate_node` wiring + tests + docs.

## What Was Changed

### Phase 47 — remaining toggle guards

**`rag/orchestrator/nodes.py` `generate_node` — `sdr_persona` (2 sites):**
- Vision path: `if sentiment != "frustrated":` → `if sentiment != "frustrated" and _node_enabled(state, "sdr_persona"):` (gates `SDR_PERSONA_OVERLAY`).
- Text path: same change, gating both the `SDR_PERSONA_OVERLAY` append **and** the `{"tools": SALES_TOOLS_SCHEMA, "tool_choice": "auto"}` binding.
- The Phase 35 frustrated-customer interlock is preserved (the toggle is AND-ed onto it, not a replacement).

**`rag/orchestrator/nodes.py` `guardrails_node` — `hitl_handover`:**
- Computes `_hitl_enabled = _node_enabled(state, "hitl_handover")` once.
- When disabled, the `update["requires_human_handover"]` no longer OR-s in `pipeline_result.requires_handover`; it preserves only the upstream flag (`bool(state.get("requires_human_handover"))`).
- The blocked-path emit block is gated to `if pipeline_result.blocked and _hitl_enabled:` — so `emit_handover_signal` (the owner notify + HITL pause) does not fire when the toggle is off.
- **Verified-safe:** a blocked answer still abstains. `guardrails_router` (nodes.py) routes on `guardrail_passed` (= `not pipeline_result.blocked`), which is untouched — never on `requires_human_handover`.

**`rag/orchestrator/product_branch.py` — `inject_product_context` + `build_carousel`:**
- Added `from rag.orchestrator.ai_settings import _node_enabled` (the file had no orchestrator-helper import; no import cycle — `ai_settings.py` imports only `Tenant`).
- `inject_product_context_node`: early-returns `{}` when the toggle is off (before any Qdrant/DB work). The downstream carousel auto-skips because `_enriched_products` stays empty.
- `build_carousel_node`: early-returns `{}` when the toggle is off, ahead of the existing `surface != "messenger"` guard.

### Phase 48 — model params into `generate_node` only

**`rag/orchestrator/nodes.py` `generate_node`:**
- Text branch: replaced `model = settings.generation_model` with `model, temperature, max_tokens = resolve_model_params(state.get("ai_settings"))`.
- Vision branch: `_, temperature, max_tokens = resolve_model_params(state.get("ai_settings"))` then re-pins `model = settings.vision_model` — images need a vision model, so `model_choice` is ignored, but tenant `temperature`/`max_tokens` apply.
- Primary `chat_complete` call: `temperature=settings.generation_temperature, max_tokens=settings.generation_max_tokens` → `temperature=temperature, max_tokens=max_tokens`.
- Tool-loop follow-up `chat_complete` (≤3 rounds, messenger/text only): same swap to the resolved locals.
- **Left locked (untouched):** the LLM-error recovery branch (`settings.generation_*`), `preprocess_vision_node` (0.0 / 100), and infra nodes `rewrite_query` / `sentiment_analysis` / `route_query` / `plan_research` (all `followup_model`, temp 0.0). None of these read `resolve_model_params`.

### Tests + Docs

- **`rag/tests/test_phase47_48_toggles_params.py`** (new) — 45 hermetic unit tests (see Verification).
- `CHANGELOG.md` — Phase 47 + Phase 48 entries in `[Unreleased]`.
- This Dev Log.

## Decisions Made

| Question | Decision |
|---|---|
| Vision path: fully locked, or honor tenant temp/tokens? | **Honor tenant `temperature`/`max_tokens`, ignore `model_choice`** (keep `vision_model`). User chose the saved-plan spec over a stricter full-lock reading. |
| `hitl_handover` disabled — should a blocked answer still abstain? | **Yes.** Gate only the handover *emission* (`emit_handover_signal` + the fresh `requires_human_handover` flag). Abstain is driven by `guardrail_passed`, so it is unaffected. |
| `abstain_node` hard-sets `requires_human_handover=True` on the terminal path. Gate it too? | **No — out of scope.** The toggle suppresses the *active* handover action (notify/pause); the terminal abstain flag is left as-is, matching the plan's stated edit point (guardrails_node only). |
| Toggle mechanism — recompile graph per tenant or early-return guards? | **Early-return guards.** The graph is compiled-once + cached; topology stays static (same pattern as `direct_fanout_node`). |
| SDR toggle vs the frustrated-customer interlock | **AND, not replace.** `sentiment != "frustrated" and _node_enabled(...)` keeps the Phase 35 safety interlock intact. |

## Verification

**New Phase 47/48 suite:**
```
45 passed in 0.38s
```

**Unit-marker regression (`pytest rag -m unit`):**
```
8 failed, 565 passed, 19 skipped, 293 deselected
```
All 8 failures are pre-existing `ingest_v2` tenant-kwarg errors (`ingest_file() missing 2 required keyword-only arguments: 'tenant_id' and 'tenant_slug'`). **Confirmed pre-existing** by stashing this session's changes and re-running the two `ingest_v2` test files on clean HEAD → identical 8 failures. **Zero net-new failures**; the 45 new tests account for the pass-count increase.

**Ruff (touched files):**
```
All checks passed!            (ruff check)
3 files already formatted     (ruff format --check)
```

## Files Touched (4)

**Modified:**
- `rag/orchestrator/nodes.py` — `generate_node` (sdr_persona ×2, Phase 48 model params ×4 edit points), `guardrails_node` (hitl_handover)
- `rag/orchestrator/product_branch.py` — `_node_enabled` import + 2 node guards
- `CHANGELOG.md`

**Created:**
- `rag/tests/test_phase47_48_toggles_params.py`
- `Dev Logs/2026-06-04 — Phases 47-48 Workflow Toggles + Model Params.md` (this file)

## Production / Deferred

- **No VPS migration or deploy this session** (per directive). The umbrella's prod cutover — including `alembic upgrade head` on the VPS for `0007_phase45_ai_settings` and a full reindex/restart — is deferred to the umbrella close.
- **Still pending in the umbrella:** the frontend Prompt Studio UI + the `GET/PUT /workspace/ai-settings` endpoint that lets tenants actually edit `ai_settings`. Until that ships, every tenant runs on the default blob (which is exactly current behavior).

## Next Phase

Frontend Prompt Studio + workspace AI-settings endpoint, then the umbrella prod cutover (migration + deploy).
