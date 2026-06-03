# Tenant AI Customization Engine — Umbrella Program (Phases 45–48)

> **Program type:** Umbrella / multi-phase (4 backend phases + frontend). Per `process/development-protocols/phase-programs.md`, advance **one phase at a time**: research subagent → execution approval → execute subagent → validate subagent → durable report/context update.
> **Recommend promoting to a feature folder** `process/features/tenant-ai-customization/` (multi-phase, 4+ plans) per CLAUDE.md feature-folder lifecycle. Kept in `general-plans/active/` per the original request; promote on first EXECUTE if desired.

---

## Context

NEXUS is being upgraded from a single-persona RAG assistant into an **enterprise white-label SaaS** where each tenant fully controls its AI's voice, knowledge boundary, conversational lifecycle, and model tuning — without code changes. The model is **Lifecycle Prompting** (à la Vapi/Retell): instead of one static system prompt, tenants define granular instructions per conversational phase (Introduction, Core Behavior, Checkout Transition, Human Handoff), toggle pipeline features on/off, and tune model parameters.

This is the next **Umbrella Program**, spanning four backend phases plus a frontend "Prompt Studio":

- **Phase 45** — Lifecycle Persona Engine (schema + prompt assembly)
- **Phase 46** — Knowledge Boundary (vector segregation **audit + harden**)
- **Phase 47** — Workflow Orchestration (node toggles)
- **Phase 48** — Model Parameters & Tuning (per-tenant)
- **Frontend** — Prompt Studio UI under `/settings/ai-studio`

### Research findings that shape the plan (verified against code at HEAD f12de47)

1. **No `workspace_configs` table.** The tenancy boundary is `app.tenants` (`Tenant`: `id, name, slug, created_at` — `rag/database/models.py:86-106`). `ai_settings` JSONB lands here, mirroring `Integration.config` JSONB pattern.
2. **Phase 46 is ~90% already shipped** (Phase 29 strict tenancy). `_tenant_filter(state)` raises on empty slug (`rag/orchestrator/nodes.py:52-70`), applied to dense+sparse; graph arm takes `tenant_id=`; product_branch has `_qdrant_filter(slug)`. Phase 46 → **audit + harden + tests + ingest-payload re-verify**, NOT net-new filtering.
3. **`NexusState` already carries `tenant_id`** (`rag/orchestrator/state.py:159`, `total=False`). Clean precedent for adding `ai_settings` as a state field.
4. **TWO state-construction sites** — the highest-risk integration fact:
   - `run_graph()` (`rag/orchestrator/graph.py:208-247`) → Messenger inbound + outbound recovery.
   - **SPA builds state inline** (`rag/routers/chat.py:174`) → `graph.astream_events(state, config)` (`rag/routers/chat.py:206`). Does NOT call `run_graph`.
   - Both must inject `ai_settings` or SPA tenants silently get no customization.
5. **`chat_complete()`** already takes per-call `model/temperature/max_tokens` (`rag/orchestrator/llm.py:107-187`). Phase 48 = read from state instead of `settings.*`.
6. **Prompt assembly** lives in `generate_node` (`rag/orchestrator/nodes.py:701-943`) with an existing overlay stack (CRM / sentiment / vision / SDR / product-continuity). Scenario prompts insert here.
7. **Sparse leak path confirmed:** `_tenant_scroll_filter(None)→None` → `_scroll_corpus(None)` scrolls the **entire collection**; `_corpora` allows a `None` key (`rag/retrieval/sparse.py:62,76-92`). Default-open gap — the one real Phase 46 fix.
8. **Frontend:** glass classes + GSAP hooks confirmed; Radix has only dialog/dropdown/popover/tooltip. **Slider/Select/Tabs/Switch NOT installed** — must add.

### Decisions locked (user-confirmed)

| # | Decision |
|---|---|
| Storage | `ai_settings` **JSONB column on `app.tenants`** (1:1, no separate table). |
| Injection vector | **AgentState field** `NexusState["ai_settings"]` (NOT RunnableConfig — no node reads config today; state is the universal currency). |
| Phase 46 scope | Audit + harden + tests **+ ingest-payload re-verify** (backfill audit: every Qdrant point carries a `tenant_id` payload; catch pre-Phase-29 orphans). |
| Model tuning scope | **Generation node only.** Infra calls (rewrite/sentiment/route/plan at temp 0.0, vision model) stay locked to settings. |
| HITL toggle semantics | Disabling `hitl_handover` → **still abstain** on blocked answers (safe fallback), but **no** HandoverSignal emitted. Validation intact; only escalation suppressed. |
| Frontend | Mount at **`/settings/ai-studio`** behind `RequireOwner`; **add** `@radix-ui/react-{slider,select,tabs,switch}` + glass-styled wrappers. |

### Safety invariant

`scenario_prompts.*` default to **empty strings**; the assembler skips empty blocks; `active_nodes.*` default **True**; `model_params.*` default **None→settings fallback**. ⇒ A tenant who never opens Prompt Studio gets **byte-identical** behavior to today. Shipping this program changes no live behavior until a tenant opts in.

---

## Shared Foundation (build first — blocks 45/47/48)

### New file: `rag/orchestrator/ai_settings.py`

Single source of truth for the blob shape and all pure accessors.

```python
DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "version": 1,
    "scenario_prompts": {
        "introduction": "",        # first-turn opener overlay
        "core_behavior": "",       # ALWAYS prepended persona/policy
        "checkout_transition": "", # buy-intent overlay
        "human_handoff": "",       # HITL overlay
    },
    "active_nodes": {              # Phase 47 — all default True (= current behavior)
        "sentiment_analysis": True,
        "research_mode": True,     # gates plan_research path via route_decision
        "inject_product_context": True,
        "build_carousel": True,
        "sdr_persona": True,       # gates SDR tools + persona overlay
        "hitl_handover": True,     # gates guardrails handover emission
    },
    "model_params": {             # Phase 48 — None => settings.* fallback
        "temperature": None,
        "max_tokens": None,
        "model_choice": None,
    },
}

def merged_ai_settings(raw: dict | None) -> dict          # deep-merge raw over DEFAULT; never KeyErrors
async def load_ai_settings(tenant_slug: str, db: AsyncSession) -> dict   # SELECT Tenant.ai_settings WHERE slug; merged; never raises
def assemble_system_prompt(base: str, ai_settings: dict, state: NexusState) -> str   # Phase 45.6
def _node_enabled(state: NexusState, key: str) -> bool    # Phase 47; default-True
def resolve_model_params(ai_settings: dict) -> tuple[str, float, int]    # Phase 48; (model, temp, max_tokens)
```

**Loader merges at load time** so nodes read complete keys with no defensive `.get` chains.

---

## Phase 45 — Lifecycle Persona Engine

### 45.1 Schema migration `0007_phase45_ai_settings.py`

New file `rag/migrations/versions/0007_phase45_ai_settings.py`, chained `down_revision = "0006_phase32_products"`, `schema="app"`.

```python
def upgrade():
    op.add_column("tenants", sa.Column(
        "ai_settings", JSONB(), nullable=False,
        server_default=sa.text("'<inlined DEFAULT_AI_SETTINGS json>'::jsonb"),
    ), schema="app")   # add_column with server_default backfills every existing tenant atomically
def downgrade():
    op.drop_column("tenants", "ai_settings", schema="app")
```

- **Inline the default JSON literal** in the migration — do NOT import `DEFAULT_AI_SETTINGS` (migrations are frozen snapshots).
- ORM: add `ai_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("..."))` to `Tenant` in `rag/database/models.py:86-106`, keep `server_default` aligned so `create_all`/tests also get defaults.

### 45.2 State field + injection

- Add to `NexusState` (`rag/orchestrator/state.py:159`, after `tenant_id`):
  ```python
  ai_settings: dict[str, Any]   # Phase 45 — merged blob; loaded at entry; never mutated mid-run
  ```
- `run_graph()` (`rag/orchestrator/graph.py:208`): add kwarg `ai_settings: dict | None = None`; in state-init set `state["ai_settings"] = merged_ai_settings(ai_settings)`.
- **Wire BOTH state sites** + outbound:

  | Site | File | How it gets the blob |
  |---|---|---|
  | SPA stream | `rag/routers/chat.py:174` | `tenant` ORM already resolved via `Depends(get_current_tenant)` → set `state["ai_settings"] = merged_ai_settings(tenant.ai_settings)`. **No extra query.** |
  | Messenger inbound | `rag/messenger/routers/webhook.py` (`_real_graph_runner`) | Has `payload.tenant_slug` → `await load_ai_settings(slug, db)` via `get_sessionmaker()`; pass `ai_settings=` into `run_graph`. |
  | Outbound recovery | `rag/messenger/routers/outbound.py` (~221) | Same `load_ai_settings(slug, db)` before `run_graph`. |

### 45.3 State-aware prompt assembly (`assemble_system_prompt`)

Pure, unit-testable. Precedence (top→bottom of returned string):

1. `base` (loaded `system_brix.md`/`system_internal.md` with `{context}`/`{question}` substituted)
2. `scenario_prompts.core_behavior` — **always** appended when non-empty (the tenant's "constitution")
3. **Exactly ONE** situational overlay, by priority:
   - `human_handoff` if `state.get("requires_human_handover")`
   - `checkout_transition` if `_is_buy_intent(state)` (reuse `state.get("_enriched_products")` — no new LLM call)
   - `introduction` if `_is_first_turn(state)` (empty `state.get("history")`)
4. **Existing overlays unchanged & in current order:** SDR → continuity → sentiment → CRM.

**Integration seam (lowest regression risk):** have `assemble_system_prompt` return only `core_behavior + situational` as a **suffix**, appended right after `rendered`/`system_content` is built and **before** the existing SDR/sentiment/CRM block (`rag/orchestrator/nodes.py:786-851`). Existing overlay code stays byte-identical. `outbound_recovery` branch (`rag/orchestrator/nodes.py:732-779`) prepends `core_behavior` only, skips situational (it owns its own lifecycle) — gate by surface.

**HITL timing caveat (document, don't fight):** at generate-time the guardrails handover hasn't run yet (guardrails is downstream). So the `human_handoff` scenario prompt applies on the turn *after* a guardrail-triggered handover (flag persists in checkpoint). Same-turn handover only comes from the pre-generate LLM-error abstain path.

**Files:** `models.py`, `migrations/versions/0007_*.py` (new), `state.py`, `graph.py`, `routers/chat.py`, `messenger/routers/webhook.py`, `messenger/routers/outbound.py`, `nodes.py`, `ai_settings.py` (new).

---

## Phase 46 — Knowledge Boundary (audit + harden + ingest re-verify)

### 46.1 Zero-trust call-site inventory (verify all present)

| Call site | File:line | Filter | Verdict |
|---|---|---|---|
| `retrieve_dense_node` | `rag/orchestrator/nodes.py:330-334` | `_tenant_filter(state)` raises on empty | SAFE |
| `retrieve_sparse_node` | `rag/orchestrator/nodes.py:340-344` | passes filter | SAFE iff slug present (path A) |
| `retrieve_graph_node` | `rag/orchestrator/nodes.py:359-363` | explicit empty-check raises | SAFE |
| `product_branch._candidate_product_ids` | `rag/orchestrator/product_branch.py:89-94` | `_qdrant_filter(slug)` incl. tenant | SAFE |
| `product_branch._enrich` | `rag/orchestrator/product_branch.py:127-132` | id+is_active only, **no tenant** | safe-by-provenance (path B) |
| `sparse.build_corpus(None)` | `rag/retrieval/sparse.py:87-159` | `None` → scroll ALL tenants | **LEAK PATH A** |

### 46.2 Hardening tasks

1. **Close path A (the real fix):** in `sparse_search` (`rag/retrieval/sparse.py:199`) reject `None` slug — default-closed:
   ```python
   tenant_slug = _extract_tenant_slug(filters)
   if tenant_slug is None:
       raise RuntimeError("sparse_search requires a tenant_id predicate (Phase 46 zero-trust)")
   ```
   Keep `build_corpus(None)` reachable only via an **explicit** boolean flag for offline diagnostics — never from a request path.
2. **Defense-in-depth path B:** add tenant scoping to `_enrich` (`rag/orchestrator/product_branch.py:127`) — `JOIN Tenant ... WHERE Tenant.slug == tenant_slug`. Makes it safe-by-construction, not just provenance.
3. **Ingest-payload re-verify (user-requested):** new script `rag/scripts/audit_tenant_payloads.py` — scroll the entire `nexus-vault` collection, assert every point payload has a non-empty `tenant_id`; report orphan point IDs (pre-Phase-29 vectors). Read-only audit; surfaces any vector that would dodge the filter. (Payload key is `"tenant_id"` holding the **slug value** — confirmed `rag/ingest_v2/pipeline.py:168`, `rag/ingest.py:174`.)

### 46.3 Test suite — new `rag/tests/test_phase46_tenant_boundary.py`

1. `sparse_search(filters=None)` → `RuntimeError`.
2. `sparse_search` with tenant-less filter → `RuntimeError`.
3. `_tenant_filter({})` → `RuntimeError` (regression guard).
4. `retrieve_graph_node` empty slug → `RuntimeError`.
5. `_enrich` excludes foreign-tenant product given a candidate-id list spanning two tenants.
6. corpus keyed per-tenant: build slug A + slug B, assert distinct `_corpora` keys, A-search never returns B chunks.
7. fuzz: tenant-A query against a monkeypatched scroll containing B chunks → zero B ids in results.

**Files:** `sparse.py`, `product_branch.py`, `scripts/audit_tenant_payloads.py` (new), `tests/test_phase46_tenant_boundary.py` (new). **Independent of 45 — can land first/in parallel.**

---

## Phase 47 — Workflow Node Toggles

### 47.1 Toggle mechanism: per-node early-return guards (graph stays statically compiled)

Graph is compiled once + cached (`get_graph` `rag/orchestrator/graph.py:192-198`). Per-tenant recompile is rejected. A disabled node returns `{}` (no-op pass-through) — same proven pattern as `direct_fanout_node` (`rag/orchestrator/nodes.py:1323-1328`). Topology never changes; only node bodies short-circuit.

### 47.2 Per-toggle behavior

| Toggle key | Edit point | Disabled behavior |
|---|---|---|
| `sentiment_analysis` | top of `sentiment_analysis_node` (`nodes.py:581`) | `return {"sentiment": "neutral"}` (explicit neutral → no overlay; keeps SDR working) |
| `research_mode` | `route_decision` router (`nodes.py:1367`) | force `return "direct_fanout"` (loop never starts; `loop_decision` already exits cleanly) |
| `inject_product_context` | top of `inject_product_context_node` (`product_branch.py:319`) | `return {}` (carousel auto-skips — reads empty `_enriched_products`) |
| `build_carousel` | top of `build_carousel_node` (`product_branch.py:371`) | `return {}` |
| `sdr_persona` | SDR conditions in `generate_node` (`nodes.py:794,837`) | add `and _node_enabled(state, "sdr_persona")` to existing gate |
| `hitl_handover` | `guardrails_node` (`nodes.py:999-1024`) | **still abstain** on block, but skip `requires_human_handover` flag + `emit_handover_signal` (per decision) |

**Non-toggleable (mandatory):** enrich_customer_profile, rewrite_query, preprocess_vision, route_query, direct_fanout, next_subquery, retrieve_{dense,sparse,graph}, fuse, rerank, accumulate_context, generate, guardrails (validation itself — only its handover emission is gated), respond, abstain.

`route_decision` is the **only** acceptable router edit (binary mode gate, not a topology rewrite):
```python
def route_decision(state):
    if not _node_enabled(state, "research_mode"):
        return "direct_fanout"
    return "plan_research" if state.get("is_research_mode") else "direct_fanout"
```

**Risks to surface in UI:** disabling `sentiment_analysis` removes the frustrated-customer SDR-suppression interlock (`nodes.py:840`) — a frustrated user could then see a checkout CTA.

**Files:** `nodes.py`, `product_branch.py`, `ai_settings.py` (`_node_enabled`). **Depends only on the state field (Phase 45.2).**

---

## Phase 48 — Per-Tenant Model Params (generation node only)

### 48.1 Resolver (`resolve_model_params`)

Precedence: validated tenant override → `settings.*` fallback. Fail-safe (never raises in hot path; out-of-bounds silently falls back).

```python
def resolve_model_params(ai_settings) -> tuple[str, float, int]:
    mp = (ai_settings or {}).get("model_params", {}) or {}
    temperature = t if isinstance((t:=mp.get("temperature")), (int,float)) and 0.0<=t<=2.0 else settings.generation_temperature
    max_tokens  = int(m) if isinstance((m:=mp.get("max_tokens")), int) and 64<=m<=8192 else settings.generation_max_tokens
    model       = c if isinstance((c:=mp.get("model_choice")), str) and c in _MODEL_ALLOWLIST else settings.generation_model
    return model, temperature, max_tokens
```

- Bounds mirror existing Pydantic constraints (`rag/config.py:134-135`: temp 0-2, max_tokens 64-8192).
- `_MODEL_ALLOWLIST = {settings.generation_model, settings.vision_model, settings.followup_model}` — the only LiteLLM-routed aliases.

### 48.2 Integration — `generate_node` text path only

- Text path: replace hardcoded `model = settings.generation_model` (`nodes.py:829`) + the `chat_complete(..., temperature=settings.generation_temperature, max_tokens=settings.generation_max_tokens)` (`nodes.py:857-858`) with the resolver triple. Tool-loop follow-ups (`nodes.py:899-904`) use the same resolved values.
- **Vision path:** keep `model = settings.vision_model` (`nodes.py:818`) — images need a vision model; apply only tenant `temperature`/`max_tokens`, never `model_choice`.
- **Outbound recovery:** leave on settings defaults (fixed transactional message; minimal blast radius).
- **Infra nodes (rewrite/sentiment/route/plan):** locked to settings (per decision — keeps retrieval deterministic).

**Files:** `nodes.py`, `ai_settings.py` (`resolve_model_params`, `_MODEL_ALLOWLIST`), `config.py` (read-only — confirm bound names).

---

## Frontend — Prompt Studio (`/settings/ai-studio`)

### Dependencies (new)
Add to `nexus-ui/package.json`: `@radix-ui/react-slider`, `@radix-ui/react-select`, `@radix-ui/react-tabs`, `@radix-ui/react-switch`.

### Routing & mount
- New route in `nexus-ui/src/App.jsx:66` under `<Route element={<RequireOwner />}>`: `<Route path="/settings/ai-studio" element={<SettingsAiStudioPage />} />`.
- Page `nexus-ui/src/pages/SettingsAiStudioPage.jsx` follows the `SettingsPage.jsx` load/loading/error pattern; `api.get('/workspace/ai-settings')` (tenant header auto-injected by `nexus-ui/src/lib/api.js:94`).

### Component architecture — `nexus-ui/src/components/settings/ai-studio/`
| Component | Role | Primitives |
|---|---|---|
| `AiStudioForm.jsx` | container; controlled state + dirty-tracking (mirror `TunableSettingsForm`); `api.put('/workspace/ai-settings', dirty)` | `usePageMountTimeline`, `.glass-card` |
| `ScenarioPromptsTabs.jsx` | 4 lifecycle prompts in **Tabs** (Introduction / Core Behavior / Checkout / Handoff) | `@radix-ui/react-tabs` + glass wrapper |
| `NodeTogglesPanel.jsx` | `active_nodes` bool map | `@radix-ui/react-switch` |
| `ModelParamsPanel.jsx` | temperature (Slider 0-2), max_tokens (Slider/number), model_choice (Select from allowlist) | `@radix-ui/react-slider`, `@radix-ui/react-select` |
| Glass wrappers | `ui/GlassTabs.jsx`, `ui/GlassSlider.jsx`, `ui/GlassSelect.jsx`, `ui/GlassSwitch.jsx` | follow inline Radix pattern of `WorkspaceSwitcher`/`CommandPalette`; apply `.glass-pane`/`.glass-dialog`; wire `useTactilePress` on triggers |

### Standards (Phase 41-44)
- `.glass-card`/`.glass-pane` on every surface; dark tint only for overlays.
- `usePageMountTimeline()` on page root; mark sections `data-animate` for stagger.
- `useTactilePress()` on buttons/switch/select triggers.
- Motion tokens from `nexus-ui/src/lib/gsap.js`.

### Backend endpoint for the UI (admin write-path)
New router `rag/routers/workspace_ai_settings.py` (or extend existing settings router):
- `GET /api/workspace/ai-settings` → `Depends(require_owner)` → return `merged_ai_settings(tenant.ai_settings)`.
- `PUT /api/workspace/ai-settings` → `Depends(require_owner)` → validate against a Pydantic schema (bounds: temp 0-2, max_tokens 64-8192, model_choice in allowlist, scenario prompt length soft-cap), persist to `Tenant.ai_settings`, return merged.
- Register in the app router table; tenant-scoped (X-Tenant-ID enforced by `get_current_tenant`).

**Files:** `package.json`, `App.jsx`, `pages/SettingsAiStudioPage.jsx` (new), `components/settings/ai-studio/*` (new), `lib/nav.js` (optional sub-nav link), `routers/workspace_ai_settings.py` (new) + router registration, `lib/api.js` (no change — `/workspace/*` is tenant-scoped by default).

---

## Sequencing

```
Phase 46 (independent)  ──► land first: pure defense, zero behavior change
        │
Shared foundation: ai_settings.py + 0007 migration + ORM column + NexusState field
        │   + run_graph kwarg + 3 call-site loaders (incl. SPA inline)   ◄── Phase 45.1-45.2
        │
        ├─ Phase 45.3  assemble_system_prompt → generate_node
        ├─ Phase 47    _node_enabled guards + route_decision edit
        └─ Phase 48    resolve_model_params → generate_node text path
        │
Frontend backend endpoint (GET/PUT /workspace/ai-settings)  ──► then Prompt Studio UI
```

Recommended order: **46 → 45 → (47 ∥ 48) → backend endpoint → frontend.** 47 and 48 are mutually independent once the state field exists.

Per `phase-programs.md`: advance **one phase at a time** — research subagent → execution approval → execute subagent → validate subagent → durable report/context update. Each phase is a `feat(...)` commit stamped `Phase 4N` in `CHANGELOG.md` + `Dev Logs/`.

---

## Risks (consolidated)

- **Two state sites** — forgetting the SPA inline path (`rag/routers/chat.py:174`) means SPA tenants silently get no customization. Highest-likelihood bug. Test both surfaces.
- **Migration default must be inlined**, not imported — else future `DEFAULT_AI_SETTINGS` edits rewrite history.
- **Empty-default invariant** — any non-empty default scenario prompt changes live behavior on deploy. Keep defaults empty.
- **HITL same-turn vs next-turn** — `human_handoff` overlay applies the turn after a guardrail handover. Set product expectations.
- **Sentiment toggle removes frustrated-SDR interlock** — surface in UI.
- **Vision/recovery model overrides blocked** — or multimodal/transactional paths break.
- **Checkpointer persistence** — `ai_settings` rides in the checkpoint; loader re-supplies fresh value each turn so a settings change takes effect next turn (no stale-checkpoint risk).

---

## Verification (end-to-end)

**Backend (per phase):**
- `cd rag && uv run alembic upgrade head` → confirm `0007` applies; `\d app.tenants` shows `ai_settings jsonb not null`. `uv run alembic downgrade -1` clean.
- `uv run pytest rag/tests/test_phase46_tenant_boundary.py -v` (7 cases green).
- `uv run python rag/scripts/audit_tenant_payloads.py` → zero orphan points (or report list).
- Existing suite unchanged: `uv run pytest` (96 files) — **regression gate: no behavior change for default-config tenant.** Add `test_ai_settings_defaults_noop` asserting a tenant with `DEFAULT_AI_SETTINGS` produces an identical system prompt to pre-Phase-45.
- New unit tests: `assemble_system_prompt` (each situational branch + precedence + empty-skip), `_node_enabled` (default-True + each toggle), `resolve_model_params` (bounds clamp + allowlist + None fallback), `load_ai_settings`/`merged_ai_settings` (partial blob upcast).
- `ruff check` + scoped `mypy --strict` on new `ai_settings.py`.

**Integration (both surfaces):**
- SPA: configure a tenant via `PUT /api/workspace/ai-settings` (non-empty `core_behavior` + `introduction`), open chat, confirm first-turn system prompt contains both (trace store / temporary log). Toggle off `sentiment_analysis` → confirm node no-ops. Set `temperature=1.5` → confirm `chat_complete` payload reflects it.
- Messenger: same via inbound webhook fixture; confirm `run_graph(ai_settings=...)` threads through.
- Cross-tenant: tenant A's custom prompt MUST NOT appear in tenant B's run.

**Frontend:**
- `cd nexus-ui && npm install && npm run build` (new Radix deps resolve) + `npm run lint` (pre-existing known warnings only).
- Manual: `/settings/ai-studio` renders behind owner guard; Tabs switch lifecycle prompts; Sliders bind temperature/max_tokens; Switches bind toggles; Select lists allowlist models; Save persists + reloads; glass + GSAP mount animation present; `prefers-reduced-motion` honored.
- E2E (Playwright MCP): owner edits a scenario prompt, saves, reloads, value persists; non-owner gets 403/redirect.

---

## New files / Modified files

**New:**
`rag/orchestrator/ai_settings.py` · `rag/migrations/versions/0007_phase45_ai_settings.py` · `rag/scripts/audit_tenant_payloads.py` · `rag/tests/test_phase46_tenant_boundary.py` · `rag/routers/workspace_ai_settings.py` · `nexus-ui/src/pages/SettingsAiStudioPage.jsx` · `nexus-ui/src/components/settings/ai-studio/{AiStudioForm,ScenarioPromptsTabs,NodeTogglesPanel,ModelParamsPanel}.jsx` · `nexus-ui/src/components/settings/ai-studio/ui/{GlassTabs,GlassSlider,GlassSelect,GlassSwitch}.jsx`

**Modified (backend):**
`rag/database/models.py` · `rag/orchestrator/state.py` · `rag/orchestrator/graph.py` · `rag/orchestrator/nodes.py` · `rag/orchestrator/product_branch.py` · `rag/retrieval/sparse.py` · `rag/routers/chat.py` · `rag/messenger/routers/webhook.py` · `rag/messenger/routers/outbound.py` · app router registration

**Modified (frontend):**
`nexus-ui/package.json` · `nexus-ui/src/App.jsx` · `nexus-ui/src/lib/nav.js` (optional)

**Docs (per phase):** `CHANGELOG.md` · `Dev Logs/` · `process/context/all-context.md` (subsystem note)
