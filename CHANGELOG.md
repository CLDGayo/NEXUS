# Changelog

All notable changes to the NEXUS Knowledge Base.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **feat(ui): complete per-page dark mode theming.** Follow-up to the core-shell dark pass — every page and sub-component now respects the theme toggle instead of showing hardcoded light colors under `.dark`. Additive sweep across ~65 `nexus-ui` components/pages (Dashboard, Documents, Chat, Conversations, Settings, AI Studio, Admin, Products, Resources, Integrations, Logs, Profile, What's New, Changelog and their sub-components): each light utility kept its class and gained a `dark:` counterpart — `bg-white`/`bg-slate-50`→`dark:bg-slate-900`, `bg-slate-100`→`dark:bg-slate-800`, `text-slate-900/800`→`dark:text-slate-100`, `text-slate-700`→`dark:text-slate-300`, `text-slate-600/500`→`dark:text-slate-400`, `border-slate-200`→`dark:border-slate-700/50`, `border-slate-100`→`dark:border-slate-800`, `border-slate-300`→`dark:border-slate-600`. Variant chains preserved (`hover:`/`focus:`/`sm:` etc. carry into the dark variant). Opacity veils (`bg-white/NN`) and the `nexus-*` palette left untouched — `.glass-*` surfaces are already handled by the shared CSS classes. Form inputs, dropdowns, and the chat input bar now read with dark backgrounds + light text in dark mode.
- **feat(ui): mobile responsive drawer, dark mode toggle, and active path fix.** UI polish sprint across the `nexus-ui` shell.
  - *Mobile drawer:* the desktop `glass-rail` sidebar is now `hidden md:flex`; on screens < `md` a hamburger (`Menu`) in `PageHeader` opens an off-canvas drawer (`MobileSidebar` in `Sidebar.jsx`) — a `z-40` backdrop + `z-50` sliding panel that closes on backdrop click, an `X` button, or nav selection. Desktop keeps its `PanelLeft` collapse button (`hidden md:flex`). Sidebar inner content extracted into a shared `SidebarContent` used by both rail and drawer. `SidebarProvider` gains non-persisted `mobileOpen`/`setMobileOpen`/`toggleMobile`.
  - *Light/Dark/System theme:* `darkMode: 'class'` added to `tailwind.config.js`; new lightweight `ThemeProvider` (`src/context/ThemeProvider.jsx`) + `useTheme` hook persist to `localStorage['nexus.theme']`, resolve `system` via `matchMedia`, and toggle `dark` on `<html>` (live-follows OS in system mode). New `ThemeToggle.jsx` (Radix dropdown, Sun/Moon/Monitor) mounted in the header right group, visible on mobile. `ThemeProvider` wraps the app outermost in `main.jsx`.
  - *Dark glass:* `.glass-pane`/`.glass-card`/`.glass-header`/`.glass-rail`/`.glass-dialog` gained `dark:` variants (dark slate veils, `border-white/10`); AppShell shell bg + ambient gradient and the Sidebar/PageHeader chrome got `dark:` counterparts.
  - *Active-path fix:* `Sidebar.jsx` no longer relies on `NavLink`'s implicit matching — `isNavActive(pathname, item)` does exact match for `end` items and a segment-boundary prefix (`to + '/'`) otherwise, so `/settings` never double-highlights with `/settings/workspaces` or `/settings/ai-studio`.
  - *Responsive grids:* `KpiCards` grid now `grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-7` with `truncate`/`min-w-0` on labels and values to prevent mobile horizontal scroll.
- **feat(ai): Phase 49 — Prompt Studio.** Owner-facing UI + HTTP surface for the Tenant AI Customization engine shipped in Phases 45–48. Workspace owners can now read and edit their tenant's `ai_settings` (persona overlays, node toggles, model params) from `/settings/ai-studio` instead of hand-editing JSONB.
- `rag/routers/workspace_ai_settings.py` — new router (`/api/workspace/ai-settings`, both endpoints `Depends(require_owner)`). `GET` returns the fully-merged blob plus a response-only `available_models` allowlist; `PUT` accepts a partial body, deep-merges over the existing blob (one level deep so untouched siblings survive), validates bounds (temperature 0–2 and max_tokens 64–8192 via Pydantic `Field`; `model_choice` against `model_choice_allowlist()` with an explicit 400), persists to `Tenant.ai_settings`, and echoes the merged result. Registered in `rag/main.py` after `api_tokens`.
- `rag/orchestrator/ai_settings.py` — extracted `model_choice_allowlist()` as the single source of truth for the allowed model ids; `resolve_model_params` now consumes it so the read-time fallback and the write-time 400 never drift.
- `rag/tests/test_phase49_ai_settings_router.py` — 7 hermetic tests: static `require_owner` lockdown guard on both handlers, Pydantic bound rejection (temperature/max_tokens/prompt length), partial-update merge correctness, and the `model_choice` allowlist (foreign id → 400 with no commit; allowlisted id round-trips).
- `nexus-ui` Prompt Studio page — `SettingsAiStudioPage.jsx` mounted at `/settings/ai-studio` under `<RequireOwner/>`, with `ScenarioPromptsTabs` (`@radix-ui/react-tabs`, 4 lifecycle textareas), `NodeTogglesPanel` (`@radix-ui/react-switch`, 6 node toggles), and `ModelParamsPanel` (`@radix-ui/react-slider` temperature + max_tokens, `@radix-ui/react-select` model). Every panel is wrapped in `.glass-pane`; the page root drives `usePageMountTimeline` (`data-animate` section cascade) and the Save button uses `useTactilePress`. GET-on-mount / PUT-dirty-sub-objects via the shared `api` client; surfaces 400/422 messages inline. New Radix deps: `react-slider`, `react-select`, `react-tabs`, `react-switch`.
- **fix(ui): sidebar double-highlight.** `nexus-ui/src/lib/nav.js` adds `end: true` to the `/settings` nav entry and `Sidebar.jsx` threads `end` onto both `NavLink` render paths, so `/settings` no longer prefix-matches its nested routes (`/settings/workspaces`, `/settings/ai-studio`) and light up twice. Adds the `AI Studio` owner nav entry.
- **chore: deploy smoke-test probe.** `deploy-rag.sh` now probes the live `POST /api/auth/jwt/login` (form-encoded, intentionally-wrong creds, expects 400/422) instead of the decommissioned `POST /api/auth/login`, preventing false alarms.
- **feat(ai): Phase 48 — Per-Tenant Model Params.** Fourth phase of the Tenant AI Customization umbrella program. Tenants can tune generation `temperature`, `max_tokens`, and `model_choice` via `ai_settings.model_params`. `resolve_model_params` is now wired into `generate_node`'s text path and the tool-call follow-up loop. The vision path keeps `settings.vision_model` but honors tenant `temperature`/`max_tokens` (`model_choice` ignored on images). The cart-recovery branch and all infra nodes (rewrite / sentiment / route / plan) stay locked to `settings.*` so retrieval stays deterministic. Fail-safe: out-of-bounds temperature (0–2), max_tokens (64–8192), or an off-allowlist model silently falls back to the settings default — never raises in the hot path. Default blob (all `None`) → byte-identical generation params.
- `rag/orchestrator/nodes.py` `generate_node` — both the text branch and the vision branch resolve `(model, temperature, max_tokens)` from `resolve_model_params(state["ai_settings"])`; the primary `chat_complete` call and the 3-round tool-loop follow-up both consume the resolved triple. Vision re-pins `model = settings.vision_model`. The LLM-error recovery branch is untouched (stays on `settings.*`).
- **feat(ai): Phase 47 — Workflow Node Toggles.** Third phase of the Tenant AI Customization umbrella program. Tenants can disable individual graph nodes via `ai_settings.active_nodes` without recompiling the statically-cached graph — each gated node early-returns a no-op, so the topology never changes (same pattern as `direct_fanout_node`). Six toggles: `sentiment_analysis`, `research_mode`, `inject_product_context`, `build_carousel`, `sdr_persona`, `hitl_handover`. `sentiment_analysis` and `research_mode` were wired alongside the Phase 45 foundation; this phase completes the remaining four. Defaults are all `True` → zero behavior change for unconfigured tenants.
- `rag/orchestrator/nodes.py` — `generate_node`'s SDR persona overlay + sales-tool binding now also gate on `_node_enabled(state, "sdr_persona")` (both text and vision paths), preserving the Phase 35 frustrated-customer interlock. `guardrails_node` gates `hitl_handover`: when disabled it neither raises a fresh `requires_human_handover` flag nor calls `emit_handover_signal`, but a blocked answer still abstains (`guardrails_router` keys off `guardrail_passed`, not the handover flag) and any upstream handover flag still rides through.
- `rag/orchestrator/product_branch.py` — `inject_product_context_node` and `build_carousel_node` early-return `{}` when their respective toggle is off; adds the `_node_enabled` import.
- `rag/tests/test_phase47_48_toggles_params.py` — 45 hermetic unit tests: `_node_enabled` default-True contract (missing key, absent `ai_settings`, empty map, explicit `True`/`False`, `None`-enables, every default toggle, single-toggle tenant isolation) and `resolve_model_params` (None/default-blob fallback, valid override, temperature + max_tokens bounds clamping including inclusive boundaries, `model_choice` allowlist enforcement across all three aliases, partial overrides) plus `merged_ai_settings` round-trip for the `active_nodes` and `model_params` sub-blobs.
- **feat(ai): Phase 45 — Lifecycle Persona Engine.** Second phase of the Tenant AI Customization umbrella program. Tenants can now define per-lifecycle-phase AI instructions (Introduction, Core Behavior, Checkout Transition, Human Handoff) stored as a JSONB blob on `app.tenants.ai_settings`. The blob is loaded at graph entry on both the SPA and Messenger surfaces and assembled into a suffix appended to the generation system prompt before the existing SDR/sentiment/CRM overlay block. Defaults are all empty strings → zero behavior change for tenants who have not configured Prompt Studio.
- `rag/migrations/versions/0007_phase45_ai_settings.py` — Alembic migration: `ADD COLUMN ai_settings JSONB NOT NULL DEFAULT <blob>` on `app.tenants`. Server default backfills every existing tenant atomically. JSON literal is inlined (not imported) so the migration is a frozen snapshot.
- `rag/orchestrator/ai_settings.py` — new module: `DEFAULT_AI_SETTINGS` canonical blob, `merged_ai_settings` deep-merge helper, `load_ai_settings` async DB loader (never raises), `assemble_system_prompt` pure prompt assembler, plus Phase 47/48 stubs (`_node_enabled`, `resolve_model_params`) that are harmless until wired.
- `rag/database/models.py` `Tenant` — `ai_settings: Mapped[dict[str, Any]]` JSONB column, `server_default` aligned with the migration.
- `rag/orchestrator/state.py` `NexusState` — `ai_settings: dict[str, Any]` field added after `cart_context`.
- `rag/orchestrator/graph.py` `run_graph` — new `ai_settings: dict | None = None` kwarg; `merged_ai_settings(ai_settings)` injected into state at entry.
- `rag/routers/chat.py` `_stream_graph_events` — `ai_settings` kwarg added; `merged_ai_settings(tenant.ai_settings)` set on state from the already-resolved Tenant ORM (no extra DB query). `chat_stream` passes `tenant.ai_settings` to the helper.
- `rag/messenger/routers/webhook.py` `_real_graph_runner` — calls `load_ai_settings(payload.tenant_slug, db)` via `get_sessionmaker()` and passes `ai_settings=` into `run_graph`.
- `rag/messenger/routers/outbound.py` `_run_cart_recovery` — same `load_ai_settings` pattern before `run_graph`; also imports `get_sessionmaker` and `load_ai_settings`.
- `rag/orchestrator/nodes.py` `generate_node` — `assemble_system_prompt` appended after `rendered`/`system_content` build and before the SDR/sentiment/CRM overlay block (both text and vision paths). `outbound_recovery` branch receives `core_behavior` only (no situational). Existing overlay code byte-identical.
- `rag/tests/test_phase45_persona.py` — 22 hermetic unit tests: `merged_ai_settings` (partial blob, None, mutation guard, unknown sub-keys), `_is_first_turn`/`_is_buy_intent` predicates, `assemble_system_prompt` (each situational branch, priority order, empty-skip, core+situational both present, whitespace-skip), and the critical `test_ai_settings_defaults_noop` regression guard (all-default blob → empty suffix across all state combinations).
- `rag/scripts/audit_tenant_payloads.py` — polished to use `rag.config.settings` (`qdrant_url`, `qdrant_api_key`, `qdrant_collection`) instead of raw `os.environ` so the script runs cleanly on the VPS with the same `.env` load path as the app.

- **feat(security): Phase 46 — Knowledge Boundary Harden & Audit.** First phase of the Tenant AI Customization umbrella program (Phases 45–48). Closes the sparse-BM25 cross-tenant leak path and adds defense-in-depth to the product-enrichment SQL query.
- `rag/retrieval/sparse.py` — zero-trust guard in `sparse_search`: raises `RuntimeError` immediately when no `tenant_id` predicate is present in the Qdrant filter, preventing fallthrough to the all-tenants BM25 corpus (Phase 46 zero-trust). `build_corpus` now requires an explicit `allow_all_tenants=True` flag to accept a `None` slug; offline diagnostic scripts must opt in.
- `rag/orchestrator/product_branch.py` — defense-in-depth tenant scope added to `_enrich`: JOINs `app.tenants` and applies `WHERE Tenant.slug == tenant_slug`, making the result safe-by-construction even if the upstream Qdrant filter were bypassed.
- `rag/scripts/audit_tenant_payloads.py` — new read-only audit script that scrolls the entire `nexus-vault` Qdrant collection and reports any point missing a `tenant_id` payload (pre-Phase-29 orphans). Exit 0 = clean, 1 = orphans found, 2 = Qdrant unreachable.
- `rag/tests/test_phase46_tenant_boundary.py` — 7-case hermetic unit test suite: sparse `filters=None` raises; sparse non-tenant filter raises; `_tenant_filter({})` regression guard; `retrieve_graph_node` empty-tenant guard; `_enrich` cross-tenant exclusion; per-tenant corpus isolation; fuzz zero-leak assertion.

## [0.16.0] - 2026-06-03

### Added
- **Phase 44 — Motion choreography + Radix polish.** Final phase of the `nexus-ui` UI/UX Modernization umbrella program: the Phase 41 GSAP hooks are wired into pages and controls, and the two hand-rolled dropdowns are upgraded to Radix. The app now reads as a kinetic, premium SaaS surface instead of a static dashboard.
- Page-mount choreography — `usePageMountTimeline()` (fade/scale-in + `data-animate` child cascade) attached to `GraphPage`, `DashboardPage`, `WhatsNewPage`, and `IntegrationsPage`. All animation routes through `useGsapContext` (`ctx.revert()`), so React StrictMode double-mounts never orphan an element at `opacity:0` (verified live — 0 stuck across pages). Honors `prefers-reduced-motion`.
- Tactile micro-interactions — `useTactilePress()` (scale `.95` on pointerdown, elastic release) on the `GraphViewSwitcher` pills (extracted into a `GraphViewPill` sub-component so the hook gets one ref per button), the `IntegrationCard` Connect button, the `WorkspaceSwitcher` trigger, and the `PremiumConnectModal` CTA.
- New unified sidebar profile dropdown — `@radix-ui/react-dropdown-menu` replaces the static profile `Link` + separate logout button in `Sidebar.jsx` with a single `glass-pane` menu (Profile + Log out).
- Header tooltips — `@radix-ui/react-tooltip` glass tooltips on the bare header icon buttons (hamburger + mobile Cmd+K), backed by a single root `Tooltip.Provider` in `App.jsx` (the Sidebar's local provider was removed as redundant).

### Changed
- `nexus-ui/src/components/tenant/WorkspaceSwitcher.jsx` — refactored from a `useState` + click-outside menu to `@radix-ui/react-dropdown-menu` (Radix owns open/close, outside-dismiss, focus); `glass-pane` content; tenant list + owner-only Manage-workspaces link preserved; selecting a workspace still calls `setActiveTenant`.
- `nexus-ui/src/components/integrations/PremiumIntegrationsGrid.jsx` — the `PremiumConnectModal` is now conditionally mounted (was always-mounted, returning `null` when closed) so the CTA is in the DOM when `useTactilePress` wires its listeners.
- `nexus-ui/src/components/graph/GraphViewSwitcher.jsx` — pills use `transition-colors` instead of `transition-all` so the CSS transition no longer fights GSAP over `transform`.

### Notes
- Intentional deviations from the literal plan, all to avoid jank or broken wiring: Integrations cascades at **panel level** (not per-card) to avoid nesting a `gsap.from` transform inside the grid panel's own transform; Dashboard marks only its always-present header because the KPI/chart blocks load async after the mount timeline runs.

## [0.15.0] - 2026-06-02

### Added
- **Phase 43 — Relation Graph Engine (`/graph`).** NEXUS now ships an interactive, physics-based force-directed graph at a new `/graph` route, visualising the real backend topology across three swappable views.
- `nexus-ui/src/lib/topology.js` — static graph spine. Exports `GRAPH_COLORS` (hex bridge mirroring `tailwind.config.js colors.nexus.*` for Canvas rendering) and three faithful subgraphs built from real backend node names: `LANGGRAPH_RUNTIME` (20 nodes, LangGraph orchestrator with conditional/barrier/loop edges), `CONVERSION_LIFECYCLE` (12 nodes, FB comment → triage → HITL → LangGraph → Stripe/GHL → cart recovery), and `ECOSYSTEM` (8 nodes, client/workspace/integration relationships + external connectors including Hunter and Akiro stubs). `SUBGRAPHS` registry + `VIEW_META` exported for switcher consumption.
- `nexus-ui/src/components/graph/graphTheme.js` — Canvas style functions for `react-force-graph-2d`: `nodeColor`, `nodeCanvasObject` (crisp circle + halo-backed label scaled by `globalScale`), `linkColor` (amber/conditional, violet/barrier, cyan/loop, slate/normal), `linkDirectionalParticles` (3 particles only when both endpoints are `state:'active'`), `linkDirectionalParticleColor`, `linkWidth`.
- `nexus-ui/src/components/graph/useGraphDimensions.js` — `ResizeObserver` hook returning `{ width, height }` from a `containerRef`; returns `width:0` until first measurement so callers can guard against mounting `<ForceGraph2D>` with a zero-dimension canvas; re-measures on sidebar collapse (reflows the flex `main`) without extra wiring; StrictMode-safe (`disconnect()` in cleanup).
- `nexus-ui/src/components/graph/RelationGraph.jsx` — `ForceGraph2D` wrapper. Owns `containerRef` + `useGraphDimensions`; renders container `div` always but mounts `<ForceGraph2D>` only when `width > 0`; transparent background; wires all theme fns; `onNodeDragEnd` pins nodes (`node.fx = node.x; node.fy = node.y`); lifts `onNodeClick` to parent.
- `nexus-ui/src/components/graph/GraphViewSwitcher.jsx` — segmented glass pill (`LangGraph Runtime | Conversion Lifecycle | Ecosystem`); controlled `value`+`onChange`; active segment accent-filled.
- `nexus-ui/src/components/graph/GraphLegend.jsx` — `glass-pane` overlay with 5 state swatches (healthy/active/paused/abstain/stub) and their meanings; bottom-left corner; `pointer-events-none`.
- `nexus-ui/src/components/graph/NodeDetailPanel.jsx` — `glass-card` panel on node click: label, state badge, group, in/out edge lists with `kind` tags; dismissible via close button; null-renders when no node selected.
- `nexus-ui/src/components/graph/GlassSpinner.jsx` — minimal `glass-pane` + lucide `Loader2 animate-spin` loader; backs the `<Suspense>` fallback while the async graph chunk loads.
- `nexus-ui/src/pages/GraphPage.jsx` — workspace assembly: `h-full overflow-hidden` container, active-view state (default `runtime`) + selected-node state; renders `RelationGraph` (fills area), `GraphViewSwitcher` (top center), `GraphLegend` (bottom-left), `NodeDetailPanel` (top-right, conditional). No backend calls — static topology only.
- `react-force-graph-2d` added to `nexus-ui/package.json` (2D Canvas variant; pulls `d3-force`; no three.js).

### Changed
- `nexus-ui/src/App.jsx` — `lazy`/`Suspense` imported from `react`; `GlassSpinner` imported; `GraphPage` declared as `lazy(() => import('./pages/GraphPage.jsx'))`; `/graph` route added inside the `AppShell` protected block (after `/resources`, not owner-gated) wrapped in `<Suspense fallback={<GlassSpinner/>}>`.
- `nexus-ui/src/lib/nav.js` — `Network` added to lucide-react import; `{ to:'/graph', label:'Graph', Icon:Network }` appended to `CORE_NAV`. Auto-populates the Cmd+K palette via `buildCommands()` with no further change.
- `nexus-ui/src/components/command/commands.js` — stale comment "No /graph command — that route lands in Phase 43" replaced with accurate note that `/graph` is auto-derived from `CORE_NAV` (Phase 43).

## [0.14.0] - 2026-06-02

### Added
- **Phase 42 — Glassmorphic App Shell + Cmd+K Command Palette + Collapsible Sidebar.** The NEXUS UI transitions from a flat white shell to a frosted-glass SaaS interface. All glass classes (`glass-rail`, `glass-header`, `glass-dialog`, `glass-overlay`, `glass-pane`) were already shipped as Phase 41 foundation tokens; Phase 42 activates them across the live app shell.
- `nexus-ui/src/lib/nav.js` — DRY nav data module. Moves `CORE_NAV`, `OWNER_NAV`, `TRAILING_NAV`, and `ADMIN_NAV_ITEM` (with their lucide-react icon imports) out of `Sidebar.jsx` into a pure `.js` module, making both the sidebar and the command palette share one authoritative nav source.
- `nexus-ui/src/context/SidebarProvider.jsx` — sidebar collapse state provider mirroring the `AuthProvider` idiom. `collapsed` boolean lazy-initialized from `localStorage.getItem('nexus.sidebar.collapsed')`, persisted to localStorage on change, memoized context value `{ collapsed, toggle, setCollapsed }`.
- `nexus-ui/src/hooks/useSidebar.js` — guarded `useContext(SidebarContext)` hook (throws if used outside `<SidebarProvider>`), matching the `useAuth.js` / `useTenant.js` pattern.
- `nexus-ui/src/hooks/useCommandPalette.js` — owns palette open state and a StrictMode-safe global `keydown` listener: `(e.metaKey || e.ctrlKey) && e.key === 'k'` → `e.preventDefault()` + toggle. Returns `{ open, setOpen }`.
- `nexus-ui/src/components/command/commands.js` — `buildCommands({ isOwner, isSuperuser })` factory; derives nav commands from `nav.js` (role-gated: OWNER_NAV only if `isOwner`, ADMIN only if `isSuperuser`) plus one `{ id:'logout', kind:'action' }` command. No `/graph` entry (Phase 43).
- `nexus-ui/src/components/command/CommandPalette.jsx` — Radix `@radix-ui/react-dialog`-based command palette. Features: case-insensitive filter, `activeIndex` keyboard navigation (ArrowUp/Down/Enter), autofocused search input, empty-state row, nav commands route via `useNavigate`, action commands (sign-out) call `logout()`. Radix provides focus-trap, Esc close, scroll-lock, and overlay-click-close. Accessible `Dialog.Title` (sr-only). Styled with `glass-dialog` + `glass-overlay`.

### Changed
- `nexus-ui/src/components/layout/AppShell.jsx` — wraps the shell in `<SidebarProvider>`, mounts ambient gradient backdrop (`bg-gradient-to-br from-blue-100/50 via-slate-50 to-violet-100/40`, `absolute -z-10`) as first child, passes `onOpenCommand` to `PageHeader`, and mounts `<CommandPalette>` as last child. Root div gains `relative` and `text-slate-900`. `<main>` and Outlet wrapper are unchanged (load-bearing for Phase 43 graph height). No `/graph` TITLES entry added.
- `nexus-ui/src/components/layout/Sidebar.jsx` — nav arrays removed from inline definitions; imported from `nav.js`. `useSidebar()` drives collapse. Root `<aside>` switches from `w-60 border-r bg-white` to `glass-rail transition-[width] duration-300` + `w-16` (collapsed) / `w-60` (expanded). Header collapses to a centered "N" glyph. Nav items wrapped in `<Tooltip.Provider>`: collapsed = icon-only NavLink + Radix right-side tooltip (`glass-pane` styled); expanded = icon + label NavLink. Footer: collapsed = stacked avatar + logout icon; expanded = current avatar/name/role/logout layout.
- `nexus-ui/src/components/layout/PageHeader.jsx` — signature gains `onOpenCommand`. Header switches from `border-b bg-white` to `glass-header sticky top-0 z-20`. Left group: `PanelLeft` hamburger button calling `useSidebar().toggle` + title. Right group: pill-shaped Cmd+K search trigger (desktop) + icon-only trigger (mobile) + existing `{right}` / `<WorkspaceSwitcher/>` / `<HealthBadge/>`.

## [0.13.0] - 2026-06-02

### Added
- **Phase 40 — Proactive Cart Recovery.** An n8n abandoned-cart workflow can now POST to a new outbound webhook that runs the existing Seina LangGraph orchestrator against the customer's existing PSID Messenger thread (continuous memory preserved) and dispatches a warm, empathetic recovery message via the Meta Graph API — all inside Meta's 24-hour standard messaging window. The endpoint returns HTTP 202 immediately; graph invocation and dispatch run in a background task registered with the same drain-on-SIGTERM registry the inbound webhook uses.
- `rag/messenger/routers/outbound.py` — new router. `POST /webhook/outbound/cart-recovery`, gated by the existing `require_webhook_api_key` (`X-Webhook-Api-Key`) dependency. `CartRecoveryRequest` / `CartItem` Pydantic models validate a non-empty `cart_id` / `psid` / `page_id`, an `AnyHttpUrl` `checkout_url`, and at least one cart item. Resolves the tenant via `resolve_tenant_for_page` and returns **422 `no_tenant_mapping`** synchronously if the `page_id` is unmapped, otherwise schedules `_run_cart_recovery` through `_default_scheduler` and returns **202** (`CartRecoveryAck`). Dispatch uses a minimal `send_text_message` httpx helper (`messaging_type:"RESPONSE"`, lawful only inside the 24h window) and logs every send as `outbound_type=cart_recovery` for future policy audit.
- **The 4 Locks — strict sequential, abort-early pre-flight gates** in `_run_cart_recovery`, each with a structured log key:
  1. **Idempotency** — `claim_cart_idempotency(cart_id)` (Redis `SET NX EX 86400`); a duplicate n8n retry within 24h is deduplicated (`cart_recovery.duplicate`).
  2. **HITL** — `is_bot_paused(psid)`; never appends an automated message to a human-handled thread (`cart_recovery.suppressed_hitl_active`).
  3. **24h window + cold PSID** — reads the Postgres checkpointer snapshot via `graph.aget_state`; aborts on empty history / no prior thread (`cart_recovery.cold_psid`), on a last-user-message timestamp older than 24h (`cart_recovery.window_expired`), and **fails closed** when no usable timestamp exists or the snapshot read errors (`cart_recovery.snapshot_failed`).
  4. **Thread lock** — wraps the graph invocation in `acquire_thread_lock(psid)` (try/finally `release_thread_lock`) to serialize against a concurrent inbound turn and prevent last-writer-wins checkpoint corruption (`cart_recovery.lock_contention`).
- `rag/messenger/idempotency.py` — new `claim_cart_idempotency(cart_id)`: atomic cart-level claim keyed `cart:idemp:{cart_id}`, TTL 86400s, fail-open on Redis error (same policy as `claim_content_idempotency`).
- `rag/orchestrator/state.py` — `Surface` literal extended with `"outbound_recovery"` (mypy-strict safe); new `cart_context: dict[str, Any] | None` state field (carries `cart_items` + `checkout_url`, never touched by the `append_history` reducer — no history leakage).
- `rag/orchestrator/graph.py` — `run_graph()` gains a `cart_context` kwarg, threaded into state at graph entry.
- `rag/orchestrator/prompts/system_recovery.md` — new dedicated recovery persona prompt (warm Seina, ≤200 chars, plain prose, no tools), with `{cart_items_block}` and `{checkout_url}` template slots.
- `rag/orchestrator/nodes.py` — `generate_node` detects `surface == "outbound_recovery"`, loads `system_recovery.md`, injects the cart context as a **SYSTEM overlay** (the directive never enters conversation history as a user turn), and **bypasses SDR tool binding** (the checkout URL is supplied directly, so no `generate_checkout_link` call). LLM errors abstain to the handover fallback.
- `rag/guardrails/pipeline.py` — the `outbound_recovery` surface bypasses the `citation` and `exact_match` validators (persuasive recovery copy + checkout URL are not RAG-cited content and would trip exact-match); the `entropy` validator still runs.
- `rag/messenger/tests/test_cart_recovery.py` (12 tests) — all four locks (idempotency duplicate, HITL paused, window-expired, cold PSID, lock contention), auth 401, payload validation, tenant-miss 422, and `thread_key == psid` identity / 202 + background dispatch.
- `rag/orchestrator/tests/test_generate_node_recovery.py` (5 tests) — recovery prompt loaded, no SDR tools bound, history non-pollution, guardrail bypass, checkout-URL injection.
- `rag/guardrails/tests/test_pipeline.py` — `TestOutboundRecoveryBypass`: confirms `outbound_recovery` bypasses citation/exact_match while entropy still runs, and that the bypass is surface-gated (a `spa` turn on the same long answer is still blocked on citation).
- Wired in `rag/main.py` (`include_router(v2_outbound.router, prefix="/webhook")`).

> **v1 scope note:** token dispatch uses the single-tenant `current_page_access_token()` overlay; the payload carries `page_id` (and the endpoint resolves+validates the tenant) for forward-compatible multi-tenant token dispatch, which is deferred. No `MESSAGE_TAG` path (24h window only); no dedicated retry/DLQ beyond the existing send-error handling.

## [0.12.0] - 2026-06-01

### Added
- **Phase 39 — SaaS Showcase Polish (integration empty states + What's New showcase).** Single-user RAG tool evolved to a presentable SaaS surface: premium integration slots with enterprise-tier upsell and a curated capability showcase page that replaces the scroll-through changelog as the default "what did we ship" surface.
- `rag/routers/integrations.py` — new read-only `GET /api/integrations/catalog` endpoint returning two static premium-connector stubs: "Hunter" (Automated Lead Verification) and "Akiro" (Advanced Analytics Processing), each `{status:"inactive", configured:false, api_token:null, tier:"enterprise"}`. New `CatalogConnector` Pydantic model. Gated by the existing `require_owner` dep. No DB, no env reads, no new settings — Messenger/LangGraph runtime loops completely untouched.
- `rag/tests/test_phase39_integrations_catalog.py` — asserts the stub contract (two connectors, all inactive/unconfigured/null token) plus a structural guard that the handler reads no DB or secrets.
- `nexus-ui/src/components/integrations/IntegrationCard.jsx` — dimmed card with status badge, min-h CLS guard, and `isConnectorConnected()` that normalises `boolean|null|undefined|""` → disconnected.
- `nexus-ui/src/components/integrations/PremiumConnectModal.jsx` — enterprise-tier upsell modal with escape/backdrop close; never fires a real connect request.
- `nexus-ui/src/components/integrations/PremiumIntegrationsGrid.jsx` — fetches `/integrations/catalog`, renders skeleton at same fixed card height as live card (CLS guard), and falls back to static stubs on fetch failure.
- `nexus-ui/src/pages/WhatsNewPage.jsx` — curated "What's New" showcase page (separate from the existing dynamic `/changelog` feed). Two sections: four active capabilities (Seina SDR, Comment Triage, HITL, GoHighLevel CRM sync) and four locked roadmap cards (multi-tenant dashboard, conversion analytics, token metering, persona studio) with `backdrop-blur-sm` + lock badge.
- `nexus-ui/src/components/whatsnew/CapabilityCard.jsx` — active feature highlight card.
- `nexus-ui/src/components/whatsnew/RoadmapCard.jsx` — locked roadmap card with `backdrop-blur-sm` overlay and lock badge.
- `nexus-ui/src/lib/whatsNew.js` — static content manifest: 4 active capabilities + 4 locked roadmap entries, all with code-grounded copy.
- Route `/whats-new` added in `nexus-ui/src/App.jsx`. `nexus-ui/src/components/layout/Sidebar.jsx`: added "What's New" nav entry → `/whats-new`, and renamed the OLD nav entry (which pointed at `/changelog` and was mislabeled "What's New") to "Changelog".
- `PremiumIntegrationsGrid` mounted in `nexus-ui/src/pages/IntegrationsPage.jsx`.

## [0.11.1] - 2026-06-01

### Changed
- **Phase 38.x — Seina persona rewrite + last-3 product dedup fix.**
- `rag/orchestrator/prompts/system_brix.md` — Messenger system prompt fully rewritten. Renamed persona to "Seina" (was an unnamed "customer service representative") and shifted tone to a warm, proactive sales rep. Added an explicit "Product recall (critical — prevents repetition)" section: state a product's name/price/stock on first mention, then use pronouns ("it", "the figure", "this one") on all subsequent turns unless the customer asks again or a new product enters the conversation. Added "Greeting & warmth" rules (bare greetings get a welcome response, never a product dump), "CRM memory & personalisation" guidance (use customer history naturally, never say "According to my records"), and "Transactional grace" guidance for checkout and lead-capture flows.
- `rag/orchestrator/product_branch.py` — `_products_already_in_history` expanded from a last-1 assistant-message check to a last-3 assistant-message check. Fixes the repetition bug where the most recent assistant turn was a pronoun-only follow-up that didn't repeat the product name, allowing the full `[Product Catalog Match]` chunk to be re-injected on the very next turn.

## [0.11.0] - 2026-05-31

### Added
- **Phase 38 — Stateless Public Comment Triage Engine.** The Messenger webhook now listens for `feed` events (public comments on Page posts), which arrive under `entry[].changes[]` rather than `entry[].messaging[]`. Each new comment is dispatched to a stateless, single-shot LLM triage call that bypasses LangGraph entirely (no state, no checkpointer, no Qdrant) and classifies intent into one of three routes: `public_only` (praise → warm public reply), `public_and_private` (product inquiry / complaint → public acknowledgement + a private DM to the commenter), or `ignore` (spam / tags). Replies are sent via the Graph API v21.0 `…/{comment_id}/comments` and `…/{comment_id}/private_replies` endpoints. Gated behind the default-off `comment_triage_enabled` flag. A strict echo guard (`from.id == page_id`) prevents the Page from triaging its own comment replies. Every failure path — unset flag, empty comment, LLM error, malformed JSON, missing page token, Graph API 4xx/5xx (including Meta's `(#10900)` stale-comment error on private replies older than 7 days) — is caught and logged; comment triage can never crash or block the DM pipeline.
- `rag/messenger/triage.py` — new module. `triage_comment(comment_text)` calls `chat_complete` on the fast 8B model (`settings.followup_model`, temperature 0.1, JSON mode via `response_format={"type": "json_object"}`) and returns a frozen `TriageResult(action, public_reply, private_reply)`. Fails closed to `TriageResult("ignore", None, None)` on any error; normalises `"null"` / empty reply strings to `None`.
- `rag/messenger/sender.py` — two standalone, fail-silent dispatchers `send_public_comment_reply` and `send_private_reply` (Graph API v21.0; `access_token` as query param; `{"message": ...}` body). They return `True`/`False` and never raise.
- `rag/messenger/routers/webhook.py` — `messenger_inbound_direct` now iterates `entry[].changes[]` for `field == "feed"` / `item == "comment"` / `verb == "add"`, applies the page echo guard, and schedules the new `_handle_comment_triage` background task (triage → public reply and, on `public_and_private`, private reply).
- `rag/config.py` — new setting `comment_triage_enabled: bool = Field(default=False)`.
- `rag/messenger/tests/test_triage.py` — unit tests for each triage route plus fail-closed paths (LLM error, malformed / non-dict JSON, invalid action, empty comment skips the LLM, `"null"` reply normalisation).
- `rag/messenger/tests/test_comment_dispatch.py` — dispatcher tests (200 → True, 400 → False, transport error → False; correct URL / token / body) and feed-webhook wiring tests (schedules triage, echo guard, flag-off, empty-message skip, and a `public_and_private` verdict dispatching both senders).

> **Operator action required (not a code change):** enable the `feed` subscription in Meta App Dashboard → Webhooks → Page (separate from `messages`), then set `comment_triage_enabled=true` (and restart `nexus-chat`) to activate the engine.

## [0.10.0] - 2026-05-31

### Added
- **Phase 37 — HITL Handover & Notification Protocol.** The Messenger bot now steps out of the way when the human owner takes over a thread via Page Inbox / Meta Business Suite, and notifies the owner via n8n the first time it fields a real customer query in a 24h session. Two Redis keys back the behaviour: `nexus:hitl:paused:{sender_id}` (TTL-backed pause flag, default 1h, auto-resume on expiry) and `nexus:hitl:notified:{sender_id}` (SET-NX once-per-24h notify dedupe). All Redis ops fail-open — a Redis outage degrades to "bot keeps replying" rather than total silence. Detection logic discriminates human-owner echoes from our own bot's outbound echoes via Facebook `app_id` matching.
- `rag/messenger/hitl.py` — new module. `is_bot_paused` / `set_bot_paused` / `clear_bot_paused` manage the pause flag. `notify_owner_if_needed` SET-NX-claims the notify slot, then POSTs `{ sender_id, page_id, thread_key, user_query, bot_answer }` (caps: 500 / 1000 chars) to `settings.n8n_webhook_notify_url`. `is_human_echo(event, our_app_id)` / `is_read_event(event)` parse Meta event shapes.
- `rag/config.py` — new settings `messenger_app_id`, `n8n_webhook_notify_url`, `hitl_pause_duration_s` (default 3600, bounded 60–86400).
- `rag/messenger/routers/webhook.py` — `messenger_inbound_direct` now intercepts `read` events and human-owner `is_echo` events at the top of the messaging loop and schedules a background pause via `_hitl_pause_on_human_activity`. The HITL gatekeeper drops inbound customer messages when `is_bot_paused(sender_id)` is True (returns `200 EVENT_RECEIVED` so Meta does not retry; releases the per-thread lock to keep state clean). `_handle_messenger_event` fires `notify_owner_if_needed` immediately after `reply_text` is generated, on both happy-path and abstention-path.
- `rag/messenger/tests/test_hitl.py` — 15 unit tests against fakeredis covering `is_read_event`, `is_human_echo`, pause set/clear/check, empty-sender short-circuit, TTL respect, webhook-unset / first-call / dedupe / 500-error / payload-cap notification paths.
- `rag/messenger/tests/test_webhook_direct.py` — `TestHITL` adds four integration tests: read-event pauses the bot and skips the graph; human-echo pauses the recipient; our own bot's echo does NOT pause; a paused sender's inbound is dropped (no graph call, no outbound dispatch).

### Changed
- `.env.example` — adds `MESSENGER_APP_ID` to the Messenger section and a new `Phase 37 — HITL Handover & Notification` section with `N8N_WEBHOOK_NOTIFY_URL` and `HITL_PAUSE_DURATION_S`.

## [0.9.0] - 2026-05-30

### Added
- **Phase 36 — Deep Commerce Context (CRM profile enrichment).** New `enrich_customer_profile_node` runs at graph entry (`START → enrich_customer_profile → rewrite_query`) on every turn. POSTs the Messenger `sender_id` (PSID) to `settings.n8n_webhook_profile_url`; n8n queries GoHighLevel CRM and returns the contact record (name, lifetime_spend, last_order_date, order_count, tags, segment, notes). The dict lands on `state["customer_profile"]`. `generate_node` then formats it into a `--- CUSTOMER CRM PROFILE ---` block prepended to the Messenger system prompt on both text-only and multimodal branches. SPA surface is never enriched (CRM data is Messenger-only). The CRM block is **ungated by sentiment** — a frustrated VIP is still recognised as a VIP. On any failure (unset webhook, empty sender_id, HTTP error, timeout, bad shape) the node returns `{"customer_profile": None}` and the graph proceeds without CRM context — never crashes.
- `rag/orchestrator/state.py` — new fields `sender_id: str` and `customer_profile: dict[str, Any] | None` on `NexusState`.
- `rag/config.py` — new optional setting `n8n_webhook_profile_url: str | None = None` under the Phase 34 n8n webhook section.
- `rag/orchestrator/nodes.py` — new helper `_format_customer_profile`; new node `enrich_customer_profile_node`; CRM-block injection in `generate_node` (text-only + vision Messenger branches).
- `rag/orchestrator/graph.py` — registers `enrich_customer_profile` node; rewires `START → enrich_customer_profile → rewrite_query`; `run_graph` gains a `sender_id: str | None = None` kwarg that, when set, populates `state["sender_id"]`.
- `rag/messenger/routers/webhook.py` — `_real_graph_runner` now passes `sender_id=payload.user_id` into `run_graph`.

## [0.8.0] - 2026-05-30

### Added
- **Phase 35 — Cognitive Empathy (sentiment routing).** New `sentiment_analysis_node` runs between `preprocess_vision` and `route_query` and classifies the raw user query into one of `{frustrated, urgent, excited, neutral}` using `settings.followup_model` (8B, `temperature=0.0`, `max_tokens=8`). `generate_node` then appends a per-sentiment behavioral overlay to the Messenger system prompt. For `frustrated`, the SDR persona overlay AND the `SALES_TOOLS_SCHEMA` tool binding are BOTH suppressed (text-only and multimodal paths) so a frustrated customer never sees a checkout CTA. `_CONTINUITY_NOTE` stays ungated by sentiment. On any LLM / parse failure the node returns `"neutral"` — the graph never crashes.
- `rag/orchestrator/state.py` — new optional `sentiment: str | None` field on `NexusState`.
- `rag/orchestrator/nodes.py` — new constants `_SENTIMENT_SYSTEM_PROMPT`, `_VALID_SENTIMENTS`, `_FRUSTRATED_OVERLAY`, `_URGENT_OVERLAY`, `_EXCITED_OVERLAY`, `_SENTIMENT_OVERLAYS`; new helper `_get_sentiment_overlay`; new node `sentiment_analysis_node`.
- `rag/orchestrator/graph.py` — registers `sentiment_analysis` node; rewires `preprocess_vision → sentiment_analysis → route_query`.
- `rag/tests/test_phase35_sentiment.py` — five tests pinning valid-category return, LLM-error fallback, unparseable-response fallback, empty-query short-circuit, and `_get_sentiment_overlay` mapping.

## [0.7.0] - 2026-05-30

### Added
- **Phase 34 — Live n8n webhook execution layer for sales SDR tools.** The two Phase 33 mock stubs (`generate_checkout_link`, `capture_lead`) are now live: each function performs an async `httpx.AsyncClient` POST to a configurable n8n webhook (`N8N_WEBHOOK_CHECKOUT_URL`, `N8N_WEBHOOK_LEAD_URL`). The checkout webhook expects an n8n → Stripe Checkout Session workflow that returns `{ "url": ... }` (with `checkout_url` / `payment_url` accepted as fallbacks); the lead webhook expects an n8n → GoHighLevel push. NEXUS remains the brain (LangGraph + LLM tool-call loop); n8n is now the hands (Stripe + CRM side effects). Connect timeout 5s; read timeout 15s for checkout, 10s for lead — chosen for Stripe Checkout cold-path round-trips.
- `rag/config.py` — new optional settings `n8n_webhook_checkout_url` and `n8n_webhook_lead_url` (both `str | None = None`). When unset, the tools fall back to descriptive mock strings so local dev and Phase 33 baseline tests continue to work without n8n.
- `.env.example` — documented Phase 34 webhook URL slots under a new "n8n sales SDR webhooks" section.
- `rag/orchestrator/tests/test_sales_tools.py` — replaced the legacy `"Phase 34"` mock assertions with six new pins (three per function): unconfigured-fallback, configured-success (mocked `httpx.AsyncClient` returning `{ "url": "https://checkout.stripe.com/cs_test_123" }` / `{ "ok": true }`), and network-error (mocked `httpx.TimeoutException`). New `_FakeResponse` / `_FakeAsyncClient` test doubles capture the POST URL and JSON body for round-trip assertion.

### Changed
- `rag/orchestrator/sales_tools.py` — module docstring updated to reflect live-integration semantics (no longer "mock stubs"). Both functions now branch on configured URL (live POST) vs. unconfigured (mock fallback). Granular exception handling: `httpx.HTTPStatusError`, `httpx.TimeoutException`, generic `Exception` (`# noqa: BLE001`) — every error path returns a descriptive string and never raises into the tool-call loop. The existing `execute_tool_call` outer safety net is preserved.

## [0.6.3] - 2026-05-30

### Fixed
- **Phase 33.3 — Messenger SDR conversational continuity & "yes" ambiguity.** Two production failures on the Messenger SDR surface, both rooted in the multi-turn pipeline blindly re-injecting product context: (1) every turn re-introduced the same catalogued product because `inject_product_context_node` unconditionally prepended `[Product Catalog Match]` chunks regardless of whether the LLM already presented them, and (2) the "yes" affirmation crashed because `ExactMatchValidator` flagged 8 anime proper nouns (`King`, `Artist`, `Special`, `Version` × 2 products) past the Phase 33.1 Messenger ceiling of 5, sending the reply to the human-handover fallback.
  - `rag/orchestrator/product_branch.py` — new `_products_already_in_history(products, history)` helper. `inject_product_context_node` now checks the most recent assistant turn; if it already mentions every current product name, the synthetic `[Product Catalog Match]` chunks are NOT prepended to `state["reranked"]`. The cached `_enriched_products` is still returned so `build_carousel_node` keeps zero round-trips.
  - `rag/orchestrator/nodes.py` — new module-level `_CONTINUITY_NOTE` and `_history_mentions_any_product(history, products)` helper. `generate_node` appends the continuity hint to the Messenger system prompt (both text-only and vision paths) whenever a prior assistant turn already mentioned any product in `state["_enriched_products"]`. Greeting / abstain turns alone do not trigger it.
  - `rag/orchestrator/nodes.py` — `guardrails_node` now extracts every `[Product Catalog Match]` chunk from `state["reranked"]` and threads the concatenated catalog text into the `query` argument passed to `_GUARDRAILS.validate(...)`. `ExactMatchValidator._retrieved_text_blob(extra=query)` then includes the full product names so franchise / anime proper nouns inside catalog names ("King", "Artist", "Special", "Version") count as grounded and never trip the suspicious-token ceiling.

### Added
- `rag/tests/test_phase32_5_product_context_injection.py` — `test_inject_node_skips_when_history_already_mentions_product`, `test_inject_node_injects_when_history_lacks_product_mention`, `test_inject_node_injects_when_history_empty`, `test_inject_node_skip_requires_ALL_product_names_in_history` (multi-product partial-mention case).
- `rag/orchestrator/tests/test_generate_sales.py` — `test_messenger_continuity_note_fires_when_history_mentions_product`, `test_messenger_continuity_note_absent_when_history_lacks_product` (greeting-only history), `test_messenger_continuity_note_absent_on_first_turn`, `test_spa_surface_never_gets_continuity_note`, `test_messenger_vision_continuity_note_fires_with_history_mention`.
- `rag/guardrails/tests/test_pipeline.py::TestCatalogTextThreading` — pins that the production "King / Artist / Special / Version" failure stays unblocked once `guardrails_node` threads the catalog text into the validator's query.

## [0.6.2] - 2026-05-30

### Fixed
- **Phase 33.2 — Messenger vision path no longer abstains on hallucinated `[n]` indices.** The vision model routinely emits out-of-bounds citation indices (e.g. `[11]` against a 4-chunk context) because multimodal models are weaker at structural formatting than text-only ones. Under Phase 33.1's `max_suspicious=5` bump the exact-match path is fine, but `CitationValidator` (severity=critical) still blocked every Messenger turn that included an image. `GuardrailsPipeline.validate()` now accepts `has_attachments: bool = False`; when `surface == "messenger" and has_attachments`, the `citation` validator is bypassed with `reason="vision-path bypass"`. `cited_ids` is still extracted from any in-bounds `[n]` markers so the Messenger surface adapter can still render source tags; out-of-bounds indices are silently dropped (the whole point of the bypass). `exact_match` and `entropy` continue to run on the vision path — grounding comes from the image itself plus the `product_branch` catalog injection, not RAG citation indices.
- `guardrails_node` now reads `state["attachments"]` and forwards `has_attachments=bool(state.get("attachments"))` to the pipeline.

### Added
- `rag/guardrails/tests/test_pipeline.py::TestVisionPathCitationBypass` — pins the four invariants: (1) Messenger+vision bypasses citation, (2) bypass preserves in-bounds `cited_ids` and drops out-of-bounds ones, (3) Messenger text-only does NOT bypass (gate on `has_attachments`), (4) SPA+vision does NOT bypass (gate on `surface`).

## [0.6.1] - 2026-05-30

### Fixed
- **Phase 33.1 — SDR / guardrail clash on Messenger.** The Phase 33 SDR persona instructs the LLM to end every Messenger reply with a CTA ("Would you like me to check stock?"), which routinely bled 3–4 common verbs and franchise nouns past `ExactMatchValidator`'s `max_suspicious=2` threshold and triggered the human-handover fallback on otherwise valid sales responses. `GuardrailsPipeline.validate()` now accepts a `surface: str = ""` kwarg; on `"messenger"` it temporarily bumps `ExactMatchValidator.max_suspicious` 2 → 5 for the duration of that call (save/restore on the singleton instance via `try/finally`, so a validator raising mid-call never leaks the bumped threshold across requests). SPA surface stays at 2.
- **Phase 33.1 — Tool calls stripped on Messenger multimodal path.** `generate_node` was passing `extra={"tools": SALES_TOOLS_SCHEMA, ...}` to `chat_complete()` even when the request carried an image. Vision models mix `image_url` content arrays with `tools` unreliably across providers, and the SDR overlay is already injected into `system_content` on the vision branch. Tool binding is now gated on `surface == "messenger" and not images`.
- **Phase 33.1 — Expanded `_PROPER_NOUN_ALLOWLIST`** with conversational SDR filler (`Would`, `Could`, `Shall`, `Should`, `Let`, `Just`, `Also`, `Sure`, `Great`, `Absolutely`, `Definitely`, `Happy`, `Like`, `Want`, `Need`, `Check`, `Look`, `Help`). Franchise-specific nouns like `One`/`Piece` are intentionally **not** added — those are handled structurally by the surface-aware threshold, not by allowlisting individual domains.

### Added
- `rag/guardrails/tests/test_pipeline.py::TestSurfaceAwareThreshold` — pins the Messenger 2→5 bump, the SPA-stays-strict invariant, and the singleton save/restore so a future refactor can't silently leak the bumped threshold across requests.

## [0.6.0] - 2026-05-30

### Added
- **Phase 33 — Autonomous Sales SDR (Messenger only).** Messenger persona is now a proactive sales rep that can autonomously call three OpenAI-compatible tools: `check_inventory` (live Postgres lookup by name within the tenant catalog), `generate_checkout_link` (mock — Phase 34 wires to Stripe/PayMongo/GCash), and `capture_lead` (mock — Phase 34 wires to CRM). SPA surface is untouched.
- `rag/orchestrator/sales_tools.py` — tool functions, OpenAI function-calling schema (`SALES_TOOLS_SCHEMA`), dispatcher with safe JSON-args parsing (`execute_tool_call`), and the `SDR_PERSONA_OVERLAY` constant that `nodes.py` appends to the Messenger system prompt at runtime (keeps `system_brix.md` neutral for non-tool flows).
- `rag/orchestrator/tests/test_sales_tools.py` and `rag/orchestrator/tests/test_generate_sales.py` — pin tool dispatch, schema shape, surface-gated tool binding, the multimodal+SDR overlay path, the 3-iteration tool-call loop cap, and the abstain-on-tool-followup-LLM-error path.

### Changed
- `LLMResult` gained an optional `tool_calls: list[dict[str, Any]] | None = None` field. `chat_complete()` now extracts `choices[0].message.tool_calls` when present so callers can react to tool invocations. Existing callers are unaffected (field defaults to `None`).
- `generate_node` now branches on `surface == "messenger"` to (a) append the SDR persona overlay to the system prompt (both text-only and multimodal paths) and (b) pass `extra={"tools": SALES_TOOLS_SCHEMA, "tool_choice": "auto"}` to `chat_complete()`. A while-loop (max 3 rounds) executes any returned tool calls and re-prompts the LLM for a final text answer; the follow-up call omits `tools` to force termination. A tool-followup LLM error abstains with `handover_reason="tool followup llm error: ..."`.

## [0.5.1] - 2026-05-29

### Fixed
- **Messenger carousel + text bubble both deliver.** `GET /api/objects/{token}` now also answers `HEAD`, returning `Content-Type`/`Content-Length` from `head_object` without draining the S3 body. Meta's Send API HEAD-probes `image_url` before queueing template messages; the prior GET-only route 405'd that probe, so Meta rejected every carousel with `(#100) ... should represent a valid URL` and DLQ'd the whole reply.
- **Text bubble no longer hostage to carousel validation.** `_dispatch_graph_api` now ships each Send API body independently — a non-retryable 400 on the carousel logs the failure and continues to the text body. Transport / 5xx / rate-limit failures enqueue only the failing body for retry instead of re-sending the bodies that already delivered.

### Added
- `rag/tests/test_objects_router.py` — pins HEAD/GET parity, 404 on missing keys, 401 on bad tokens.
- `rag/messenger/tests/test_sender_graph_api.py` — pins per-body dispatch isolation + `image_urls`/`image_fingerprint` log fields.

### Changed
- `outbound.graph_api` info log now emits `image_urls=<n>` and `image_fingerprint=<sha256[:12]>` on every dispatch so future Meta validation regressions are debuggable from logs alone.

## [0.5.0] - 2026-05-28

### Fixed
- **Products no longer stuck "Pending" in Documents.** Product Qdrant payload now carries `file`, `title`, `text`, `heading_path`, `folder`, `source_kind="product"` so `_qdrant_index_summary` aggregates product chunks and the Documents UI flips to "Indexed".
- **Chat citations show product names, not raw UUIDs.** Same payload enrichment lets the citation renderer label sources as e.g. `[1] Luffy Gear 4 Bound man` instead of the Qdrant point id, and gives the LLM real anchor text for product-related questions.
- **Messenger inbound dropped with `no_tenant_mapping`.** Operator-facing `seed_messenger_page` CLI binds a Facebook Page id to its owning tenant (idempotent, `ON CONFLICT DO UPDATE`). Inbound webhook now resolves Cozy Downloads Store events end-to-end.

### Added
- `rag/scripts/reupsert_products.py` — backfill the enriched product payload into Qdrant for existing rows; tenant-scoped via `--tenant`.
- `rag/scripts/seed_messenger_page.py` — bind `(facebook_page_id, tenant_slug)`; supports `--list-tenants` for discovery.
- `rag/tests/test_phase32_3_product_payload.py`, `rag/tests/test_phase32_3_reupsert_script.py`, `rag/tests/test_phase32_3_seed_messenger_page.py` — pin the payload contract and CLI surface.

### Changed
- `CLAUDE.md` Definition of Done now requires a CHANGELOG entry for any user-visible change. The What's New page is part of "done".

## [0.4.5] - 2026-05-28

### Added
- **Products surface in Documents view.** Phase 32.2 unions `app.documents` (vault notes) and `app.products` (catalogue) under a synthetic `/products/{slug}` folder so the SPA renders the full tenant artifact set.
- **Object-proxy token + presign serializer.** Image URLs in `/products` payloads are minted as 1-hour presigned MinIO GETs at serialization time when `MINIO_PUBLIC_BASE_URL` is unset, fixing broken-icon thumbnails in the carousel editor and product list.

### Fixed
- **Chat session "404 not found" on first send.** Backend now lazy-creates the `app.chat_sessions` row on the first `/api/chat/stream` POST instead of refusing client-minted UUIDs.
- **Image uploader hidden on new-product form.** Dropped the `isEditing` gate; the carousel now stages local blobs and flushes them to MinIO after `createProduct` resolves.

## [0.4.4] - 2026-05-28

### Fixed
- **Duplicated top nav on `/products` pages.** Removed page-level `PageHeader`; relocated affordances into inline toolbars and extended `AppShell.TITLES` with a regex fallback for `/products/:id`.
- **Broken-icon thumbnails in product list and carousel editor.** `_serialize_image` now `await`s a presigned URL whenever `public_url_for()` returns `None`. Parallel presigns batched with `asyncio.Semaphore(20)`.

## [0.4.3] - 2026-05-28

### Added
- **Phase 32 — Product Catalog + Meta Carousels.**
  - `app.products` + `app.product_images` (migration `0006`) with `(tenant_id, slug)` uniqueness, `price_cents >= 0`, `quantity >= 0` CHECK constraints.
  - `/api/products` CRUD, multipart image upload (Pillow → WebP, 1200px edge, configurable cap), drag-reorder with negative-offset swap, MinIO + Qdrant cleanup on delete.
  - `rag/products/sync.py` — deterministic `uuid5` point id, `upsert_product_to_qdrant` (embeds name + description with bge-small), idempotent delete.
  - Messenger product carousel via Meta Generic Template — `enrich_with_products_node` filters Qdrant by `kind=product+is_active=true+tenant_id`, JOINs Postgres for `quantity > 0` source-of-truth.
  - SPA `Products` page (owner-only) — search, grid, optimistic delete, edit form with image staging.

### Security
- Every product route gated by `require_owner` + tenant-scoped SQL filter. Cross-tenant rebind on `messenger/pages` returns 409.

## [0.4.2] - 2026-05-27

### Added
- **Phase 29.2 — Messenger ↔ Tenant binding.** `app.messenger_page_tenants` table (migration `0003`); inbound webhook now resolves owning tenant from `page_id` before scheduling the orchestrator run. Unmapped pages drop with structured `messenger.event.no_tenant_mapping` log; never default to a fallback tenant (closes the Phase 29 cross-tenant leak).
- Frontend tenant context injected via `X-Tenant-ID` header on every authenticated request.

## [0.4.1] - 2026-05-15

### Added
- **Phase 28.2 — Minio avatar uploads.** User avatars stored in tenant-scoped MinIO bucket; UI avatar picker with crop preview.
- **Dashboard tenancy fix.** KPIs now filter by `tenant_id` end-to-end; previously cross-tenant counts leaked into the Dashboard.

### Changed
- `mypy --strict` is now clean on the full `rag/` tree.

## [0.4.0] - 2026-05-15

### Added
- **Settings** page — user-tunable retrieval params (TOP_K, RETRIEVE_K, CHUNK_TOKENS, semantic/rerank thresholds), model picker (Groq + follow-up), theme toggle, password change, and JWT rotate.
- **What's New** page — sidebar entry with unread red-dot badge; renders this CHANGELOG.md.
- **Integrations** page — connect outbound webhooks (n8n/Make), Slack, Discord, and GitHub; subscribe to `ingest.*` and `chat.*` events; per-integration test-fire.
- **API tokens** — scoped Bearer tokens (`nxs_…`) for programmatic access to chat, documents, and dashboard endpoints. Plaintext shown once at creation.
- **Resources** page — prompt + template library backed by `<VAULT>/03 - Resources/prompts/`. Activate a prompt as the system prompt for chat; idempotent default-prompt seeding.
- **Event bus** (`rag/events.py`) — in-process async pub/sub feeding the integrations dispatcher. Events: `ingest.complete`, `ingest.failed`, `chat.complete`, `chat.feedback.up`, `chat.feedback.down`, `chat.error`.

### Changed
- `auth.py` + `deps.py` now read password + JWT secret from a filesystem overlay (`data/.password_override.json`) when set, falling back to env. Enables rotation without redeploy.
- `chat.py` reads `system_prompt_id`, `TOP_K`, `RERANK_CONFIDENCE_FLOOR`, and model names from the settings table at request time.

### Security
- Passwords stored as scrypt hash + per-installation salt in the overlay file (mode 600). Plaintext never persisted.
- API tokens stored as SHA-256 hashes; revocation is immediate (checked on every request, no cache).

## [0.3.0] - 2026-05-14

### Added
- Documents upload + archive endpoints with content-hash dedup and vector GC.
- Dashboard observability surface — KPIs, health pills, 7-day charts.
- Conversations history persistence (SQLite).

### Changed
- Migrated systemd unit from Chainlit to FastAPI/uvicorn (`app:app`).
- Mac dev connects to Qdrant via public HTTPS endpoint; no SSH tunnels.

## [0.2.0] - 2026-05-09

### Added
- Initial RAG pipeline — layout-aware Markdown chunking, fastembed (BAAI/bge-small-en-v1.5), Qdrant, Groq streaming.
- Single-password JWT auth + SPA shell (Dashboard, Documents, Chat, Conversations, Logs).
