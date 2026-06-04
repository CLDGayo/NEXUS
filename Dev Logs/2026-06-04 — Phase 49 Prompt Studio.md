# 2026-06-04 — Phase 49 Prompt Studio

Closes the Tenant AI Customization umbrella (Phases 45–48) by giving the
already-shipped `ai_settings` engine a read/write HTTP surface and an
owner-facing UI. Also folds in two cleanups requested alongside.

## What shipped

### Prompt Studio backend
- **New router** `rag/routers/workspace_ai_settings.py` mounted at
  `/api/workspace/ai-settings`. Both endpoints gate on `require_owner`.
  - `GET` → `merged_ai_settings(tenant.ai_settings)` + response-only
    `available_models` (the model_choice allowlist) so the UI Select renders
    options without a second request.
  - `PUT` → partial body (`scenario_prompts` / `active_nodes` / `model_params`,
    all optional). Deep-merges one level over the existing blob (untouched
    siblings survive), validates bounds, persists to `Tenant.ai_settings`,
    echoes the merged result.
- **Bounds**: temperature 0–2 and max_tokens 64–8192 enforced by Pydantic
  `Field(ge/le)` (early 422). `model_choice` is checked against
  `model_choice_allowlist()` with an explicit 400 (Pydantic can't express a
  runtime-settings-derived allowlist).
- **Refactor**: extracted `model_choice_allowlist()` in
  `rag/orchestrator/ai_settings.py` as the single source of truth;
  `resolve_model_params` now consumes it, so the read-time silent fallback and
  the write-time 400 share one list and never drift.
- **Tests** `rag/tests/test_phase49_ai_settings_router.py` — 7 hermetic cases:
  static `require_owner` lockdown on both handlers, Pydantic bound rejection,
  partial-merge correctness, and the model_choice allowlist (foreign → 400 no
  commit; allowlisted → round-trip + persist).

### Prompt Studio frontend
- `SettingsAiStudioPage.jsx` at `/settings/ai-studio` under `<RequireOwner/>`.
  GET-on-mount, dirty-tracking, PUT-the-three-sub-objects on Save, inline
  400/422 surfacing via the shared `api` client.
- Sub-components in `nexus-ui/src/components/aistudio/`:
  - `ScenarioPromptsTabs` — `@radix-ui/react-tabs`, 4 lifecycle textareas
    (introduction / core_behavior / checkout_transition / human_handoff).
  - `NodeTogglesPanel` — `@radix-ui/react-switch`, 6 node toggles (off = explicit
    false, matching backend `_node_enabled` default-True).
  - `ModelParamsPanel` — `@radix-ui/react-slider` (temperature + max_tokens,
    number input mirror) and `@radix-ui/react-select` (model, "Default" = null).
- **Standards**: every panel wrapped in `.glass-pane`; page root drives
  `usePageMountTimeline` (`data-animate` section cascade); Save button uses
  `useTactilePress`.
- New deps: `@radix-ui/react-slider`, `react-select`, `react-tabs`, `react-switch`.

### Cleanups
- **Sidebar double-highlight** — `nav.js` gives `/settings` `end: true` and
  `Sidebar.jsx` threads `end` onto both `NavLink` paths, so `/settings` stops
  prefix-matching `/settings/workspaces` and the new `/settings/ai-studio`.
  Added the `AI Studio` owner nav entry.
- **Deploy smoke test** — `deploy-rag.sh` now probes `POST /api/auth/jwt/login`
  (form-encoded, wrong creds, expect 400/422) instead of the decommissioned
  `POST /api/auth/login`.

## Notes / follow-ups
- `PUT` uses `exclude_none`, so sending `model_choice: null` does not clear a
  previously-pinned model (the key is dropped, existing value survives). The UI
  "Default" option therefore won't reset an already-set choice until a
  clear-semantics tweak lands — acceptable for v1.
- VPS still needs `alembic upgrade head` for the Phase 45 `ai_settings` column
  (carried over from the umbrella backlog).

## Verification
- `uv run pytest tests/test_phase49_ai_settings_router.py` → 7 passed.
- App import: `/api/workspace/ai-settings` GET+PUT mounted.
- `ruff check` clean on new/edited Python.
- `npm run lint` + `npm run build` (frontend gate).
