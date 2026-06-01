# Phase 39 — SaaS Showcase Polish: Integration Empty States + What's New

**Date:** 2026-06-01
**Owner:** Clarence Lloyd Gayo
**Versions shipped:** `0.11.1` (Phase 38.x persona/dedup), `0.12.0` (Phase 39 showcase)

## Context

NEXUS has been a functional single-user RAG tool since Phase 27 (IAM) and has steadily grown in Messenger/SDR sophistication through Phases 33–38. Phase 39 shifts the lens: how does a potential SaaS customer experience the product surface? Two gaps were clear:

1. The Integrations page showed only live connectors (Messenger + workspace). Premium connector slots were absent — a SaaS visitor sees empty space where they expect to see what they'd get when they upgrade.
2. The changelog feed is a developer-facing scroll. There was no curated "what can this thing do for me" surface for non-technical evaluators or stakeholders.

Three decisions were locked before implementation:

| Question | Decision |
|---|---|
| New "What's New" page or augment existing `/changelog`? | New separate page (`/whats-new`). Changelog stays untouched as a technical feed. |
| Real integration endpoints or lightweight static stubs? | Lightweight catalog endpoint (`GET /api/integrations/catalog`) — no DB, no new settings, runtime loops untouched. |
| Scope? | `nexus-ui/` only for frontend; one new read-only route in `rag/routers/integrations.py`. No orchestrator or Messenger changes. |

## Phase 38.x — Seina Persona Rewrite + Last-3 Product Dedup

A targeted refinement shipped in the same session (commit `3b2a336`) before Phase 39.

**Persona rewrite (`rag/orchestrator/prompts/system_brix.md`):** The Messenger system prompt was rewritten. The persona is now named "Seina" (was an unnamed customer service representative). The tone shifts to a warm sales rep. The critical addition is a "Product recall" rule: state a product's name/price/stock on first mention, then use pronouns on all subsequent turns in the same thread unless the customer asks again or a new product enters. Supporting rules: bare greetings get warmth (no product dump); CRM history surfaces naturally (never "According to my records"); transactional grace guides checkout and lead-capture copy.

**Dedup gate (`rag/orchestrator/product_branch.py`):** `_products_already_in_history` was expanded from a last-1 to a last-3 assistant-message scan. The previous single-turn check missed when the most recent assistant turn was a pronoun-only follow-up that contained no product name — the dedup gate would pass, re-injecting the full `[Product Catalog Match]` block and prompting Seina to re-introduce the product she had already described. Checking three turns back catches this.

No new tests in 38.x — this was a prompt-and-heuristic adjustment to already-tested logic.

## What Was Built — Phase 39

### Backend

- `rag/routers/integrations.py` — `GET /api/integrations/catalog` returns two static premium-connector stubs:
  - "Hunter" — Automated Lead Verification
  - "Akiro" — Advanced Analytics Processing
  - Both: `{status:"inactive", configured:false, api_token:null, tier:"enterprise"}`.
  - New `CatalogConnector` Pydantic model. Gated by the existing `require_owner` dependency.
  - No DB reads, no env reads, no new settings. The Messenger webhook and LangGraph loop are completely untouched.

- `rag/tests/test_phase39_integrations_catalog.py` — asserts the stub contract (two connectors, all inactive/unconfigured/null token) and a structural guard that the handler exercises no DB or secret dependencies.

### Frontend — Integration Empty States

- `nexus-ui/src/components/integrations/IntegrationCard.jsx` — dimmed premium card. `isConnectorConnected()` normalises `boolean|null|undefined|""` → disconnected so no edge-case render breaks.
- `nexus-ui/src/components/integrations/PremiumConnectModal.jsx` — enterprise-tier upsell modal. Escape and backdrop both close it. Never fires a real connect API call.
- `nexus-ui/src/components/integrations/PremiumIntegrationsGrid.jsx` — fetches `/integrations/catalog` on mount. Skeleton renders at the same fixed height as the card (CLS guard). On fetch failure, falls back to static hardcoded stubs so the section always renders.
- Mounted in `nexus-ui/src/pages/IntegrationsPage.jsx`.

### Frontend — What's New Showcase

- `nexus-ui/src/pages/WhatsNewPage.jsx` — curated capability showcase, intentionally separate from the existing dynamic `/changelog` feed.
- Section A (Active): 4 live capabilities — Seina SDR, Comment Triage, HITL Handover, GoHighLevel CRM Sync. Each with code-grounded copy.
- Section B (Roadmap): 4 locked cards — Multi-Tenant Dashboard, Conversion Analytics, Token Metering, Persona Studio. Each with `backdrop-blur-sm` + lock badge.
- `nexus-ui/src/components/whatsnew/CapabilityCard.jsx` — active feature card component.
- `nexus-ui/src/components/whatsnew/RoadmapCard.jsx` — locked roadmap card with blur overlay.
- `nexus-ui/src/lib/whatsNew.js` — static content manifest for both sections.
- Route `/whats-new` added in `nexus-ui/src/App.jsx`.
- `nexus-ui/src/components/layout/Sidebar.jsx`: "What's New" nav entry added (→ `/whats-new`). The old Sidebar entry that was labeled "What's New" but pointed at `/changelog` was renamed to "Changelog" — correcting a mislabel that existed since the feed launched.

## Verification

- **Backend:** `ruff check` + `ruff format` → clean. `uv run pytest rag/tests/test_phase39_integrations_catalog.py` → **18 passed** (catalog + integrations + owner-gate + app-mount smoke).
- **Frontend:** `npm run build` (Vite 6) → **clean build**. All new JSX compiled and bundled successfully.

## Tech Debt Note

`npm run lint` is non-functional in `nexus-ui/`. The `package.json` lint script references `eslint` but ESLint is not installed and there is no `.eslintrc`/`eslint.config.*` file. This was pre-existing before Phase 39 — not introduced here. Front-end lint coverage is currently zero. Recommend wiring ESLint + `eslint-plugin-react` in a follow-up before any automated CI gate is added.

## Architect's decisions honoured

| Question | Decision shipped |
|---|---|
| Catalog source of truth | Static stubs in the route handler — no DB migration needed. Stubs are the spec; real connectors are a future feature branch. |
| CLS guard approach | Fixed `min-h` on `IntegrationCard` + skeleton at same height as card. |
| Modal behaviour | Enterprise upsell copy only — the modal never calls the connect API. |
| Showcase vs. changelog | Separate route and page. `/changelog` is untouched. |
| Sidebar rename | Old "What's New" → "Changelog" to remove the mislabel; new "What's New" → `/whats-new`. |

## Deferred / Follow-up

- ESLint install + config for `nexus-ui/` (pre-existing tech debt, flagged above).
- Real connector wiring for Hunter and Akiro (catalog stubs are the placeholder; implementation is a future feature branch).
- E2E Playwright spec for the integration cards and `/whats-new` page.

## Operational notes

No deploy action needed beyond normal `./deploy-rag.sh`. No new env vars, no DB migration, no systemd changes. The catalog endpoint is live once the API restarts.
