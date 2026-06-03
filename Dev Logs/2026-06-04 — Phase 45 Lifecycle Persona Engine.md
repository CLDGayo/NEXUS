# Phase 45 — Lifecycle Persona Engine

**Date:** 2026-06-04
**Owner:** Clarence Lloyd Gayo
**Program:** Tenant AI Customization Umbrella (Phases 45–48)
**Version:** Unreleased

## Context

Phase 45 is the second phase of the Tenant AI Customization umbrella program (Phase 46 landed first per the sequencing decision — it was independent and closed real security gaps).

NEXUS is evolving from a single-persona RAG assistant into an enterprise white-label SaaS where each tenant controls its AI's conversational lifecycle. Phase 45 establishes the storage layer, state injection, and prompt assembly engine. Future phases (47 node toggles, 48 model params) build directly on the `NexusState["ai_settings"]` field and `ai_settings.py` module shipped here.

**Safety invariant:** all `scenario_prompts.*` default to empty strings; `assemble_system_prompt` skips empty blocks; `active_nodes.*` default True; `model_params.*` default None. A tenant who never opens Prompt Studio gets byte-identical behavior to today.

## What Was Changed

### Step 0 — Audit Script Polish (`rag/scripts/audit_tenant_payloads.py`)

Replaced raw `os.environ.get("QDRANT_URL")` / `os.environ.get("QDRANT_API_KEY")` / `os.environ.get("QDRANT_COLLECTION")` lookups with `from rag.config import settings` and `settings.qdrant_url`, `settings.qdrant_api_key`, `settings.qdrant_collection`. This loads `.env` the same way the running app does, so the script works correctly on the VPS without any extra env setup. Graceful "unreachable → clear error, exit 2" behavior is unchanged.

### Step 1 — Schema Migration + ORM

**`rag/migrations/versions/0007_phase45_ai_settings.py`** — new Alembic migration:
- `down_revision = "0006_phase32_products"`, `revision = "0007_phase45_ai_settings"` (confirmed head via `alembic show`)
- `upgrade()`: `op.add_column("tenants", sa.Column("ai_settings", JSONB(), nullable=False, server_default=sa.text("'<blob>'::jsonb")), schema="app")`
- `downgrade()`: `op.drop_column("tenants", "ai_settings", schema="app")`
- JSON literal is **inlined**, not imported from `ai_settings.py` — migrations are frozen snapshots

**`rag/database/models.py`** `Tenant` class:
- Added `ai_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'...'::jsonb"))`
- `server_default` aligned with the migration blob

### Step 2 — Foundation Module + State + Injection

**`rag/orchestrator/ai_settings.py`** (new file):
- `DEFAULT_AI_SETTINGS` — canonical blob with `version`, `scenario_prompts` (4 keys, all `""`), `active_nodes` (6 keys, all `True`), `model_params` (3 keys, all `None`)
- `merged_ai_settings(raw)` — deep-merge raw over default; never KeyErrors; never mutates default; unknown sub-keys preserved
- `load_ai_settings(tenant_slug, db)` — async DB loader via `select(Tenant.ai_settings).where(Tenant.slug == slug)`, returns merged; never raises (logs WARNING and returns default on any exception)
- `assemble_system_prompt(base, ai_settings, state)` — Phase 45.3 suffix assembler (see Step 3)
- `_node_enabled(state, key)` — Phase 47 stub: default-True toggle helper
- `resolve_model_params(ai_settings)` — Phase 48 stub: `(model, temp, max_tokens)` resolver with bounds validation and settings fallback

**`rag/orchestrator/state.py`** `NexusState`:
- Added `ai_settings: dict[str, Any]` after `cart_context` with Phase 45 comment

**`rag/orchestrator/graph.py`** `run_graph`:
- Added `ai_settings: dict | None = None` kwarg
- Imported `merged_ai_settings` from `rag.orchestrator.ai_settings`
- Set `state["ai_settings"] = merged_ai_settings(ai_settings)` unconditionally in state init

**`rag/routers/chat.py`** (SPA surface):
- Added `ai_settings: dict[str, Any] | None = None` param to `_stream_graph_events`
- Imported `merged_ai_settings`
- Set `"ai_settings": merged_ai_settings(ai_settings)` in the inline state dict
- Updated `chat_stream` call site to pass `ai_settings=tenant.ai_settings` (no extra DB query — `tenant` ORM already resolved by `Depends(get_current_tenant)`)

**`rag/messenger/routers/webhook.py`** `_real_graph_runner`:
- Added lazy imports: `get_sessionmaker`, `load_ai_settings`, `run_graph`
- Opens a session via `get_sessionmaker()` when `payload.tenant_slug` is set
- Passes `ai_settings=` into `run_graph`

**`rag/messenger/routers/outbound.py`** `_run_cart_recovery`:
- Added `get_sessionmaker`, `load_ai_settings` imports at module level
- Opens a session and calls `load_ai_settings(tenant_slug, db)` before `run_graph`
- Passes `ai_settings=ai_settings_blob` into `run_graph`

### Step 3 — Prompt Assembly Integration

**`rag/orchestrator/ai_settings.py`** `assemble_system_prompt`:
- Pure function returning the Phase 45 SUFFIX only (not the full prompt)
- `core_behavior` always appended when non-empty
- Exactly one situational overlay, priority: `human_handoff` (if `requires_human_handover`) > `checkout_transition` (if `_enriched_products`) > `introduction` (if no history)
- Empty entries skipped — whitespace-stripped before check
- Returns `""` for all-default tenants

**`rag/orchestrator/nodes.py`** `generate_node`:
- Added `from rag.orchestrator.ai_settings import assemble_system_prompt` import
- Text path: `_persona_suffix = assemble_system_prompt(base=..., ai_settings=state.get("ai_settings") or {}, state=state)` appended to `messages[0]["content"]` with `"\n"` separator, BEFORE the Phase 33 SDR/sentiment/CRM overlay block
- Vision path: same `_persona_suffix` injection at the same seam (the persona suffix block covers both paths since it's placed after the if/else that builds `system_content` / `rendered`)
- `outbound_recovery` branch: `core_behavior` only, applied directly to `rendered_recovery` before building `recovery_messages`
- All existing overlay code (SDR, continuity, sentiment, CRM) stays byte-identical

### Step 4 — Docs

- `CHANGELOG.md` — Phase 45 entry in `[Unreleased]`
- This Dev Log

## Decisions Made

| Question | Decision |
|---|---|
| SPA path: pass tenant ORM or do extra query? | Pass `tenant.ai_settings` directly from the already-resolved `Depends(get_current_tenant)` object — zero extra DB query. |
| Messenger: where to open the session? | Mirror `product_branch._enrich` pattern: `get_sessionmaker()` + `async with sessionmaker() as db`. Lazy import to avoid heavy chain in test environments. |
| Prompt suffix vs full prompt replacement? | Suffix only (appended after `rendered`/`system_content`). Existing overlays stay byte-identical. Lowest regression risk. |
| `_persona_suffix` placement vs vision/text split? | Single injection block placed after the `if images / else` builds both paths, before Phase 33. The suffix injection is surface-agnostic; surface-specific behavior (SDR, CRM) is handled by the existing block below. |
| Phase 47/48 stubs: ship now or later? | Shipped now as pure helpers with no graph wiring. Harmless: not called from any hot path. Avoids a separate "add stub" PR when Phase 47 lands. |

## Verification

**Phase 45 test run:**
```
22 passed in 0.35s
```

**Full suite (baseline comparison):**
```
Pre-Phase-46:  9 failed, 784 passed, 25 skipped
Post-Phase-46: 9 failed, 784 passed, 25 skipped (Phase 46 dev log)
Post-Phase-45: 8 failed, 807 passed, 25 skipped
```
The 8 remaining failures are all pre-existing `ingest_v2` tenant-kwarg errors (`index_file_links()` / `ingest_file()` missing `tenant_id` / `tenant_slug`). Zero net-new failures introduced. The count change (9→8 failed, 784→807 passed) reflects 22 new Phase 45 tests plus one pre-existing failure (`test_phase32_2_object_proxy_token`) that resolved between sessions.

**Alembic:**
- `alembic show 0007_phase45_ai_settings` → `Rev: 0007_phase45_ai_settings (head)`, `Parent: 0006_phase32_products`. Migration chain correct.
- `alembic upgrade head --sql` fails in offline mode due to pre-existing `0005_phase31_security_and_docs.py` rowcount issue (rowcount attribute unavailable in offline SQL generation). This is a pre-existing constraint; live DB upgrade on VPS is the correct verification path.

**Ruff:**
```
All checks passed! (ruff check)
11 files already formatted (ruff format --check)
```

## Files Touched (11)

**Modified:**
- `rag/database/models.py`
- `rag/orchestrator/state.py`
- `rag/orchestrator/graph.py`
- `rag/orchestrator/nodes.py`
- `rag/routers/chat.py`
- `rag/messenger/routers/webhook.py`
- `rag/messenger/routers/outbound.py`
- `rag/scripts/audit_tenant_payloads.py`
- `CHANGELOG.md`

**Created:**
- `rag/orchestrator/ai_settings.py`
- `rag/migrations/versions/0007_phase45_ai_settings.py`
- `rag/tests/test_phase45_persona.py`
- `Dev Logs/2026-06-04 — Phase 45 Lifecycle Persona Engine.md` (this file)

## Next Phase

Phase 47 — Workflow Node Toggles. Depends only on `NexusState["ai_settings"]` field (shipped here). Wire `_node_enabled(state, key)` (already implemented in `ai_settings.py`) into individual node guards per the plan's toggle table.
