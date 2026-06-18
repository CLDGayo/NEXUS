# Plan: Facebook Comment-to-Message Automations UI (Phase 57.2 — frontend)

> **STATUS: ✅ SHIPPED + DEPLOYED (2026-06-18).** Frontend commit `9018c69`; full
> `feat/fb-comment-to-message` branch deployed to VPS (migration 0014 applied; 0012/0013/0014 all live).
> CRUD API verified against the live backend — POST 201 / PUT 200 / DELETE 204. Companion to the engine
> plan `facebook-comment-to-message_PLAN_18-06-26.md` (Phase 57) and API (Phase 57.1).

## Context

Phase 57 shipped the deterministic keyword Private-Reply engine; Phase 57.1 shipped the tenant-scoped
CRUD REST API at `/api/tenants/{tenant_id}/facebook/automations` (GET/POST/PUT/DELETE, gated by
`require_manager`). Before this, rows could only be created via raw SQL or curl. Phase 57.2 built the
React frontend so a workspace manager can visually create, list, toggle, edit, and delete keyword
automations.

Two facts that shaped the build:
1. **Repo is plain JavaScript (JSX), not TypeScript** — the "FacebookAutomation interface" was delivered
   as a JSDoc `@typedef`, the project's only typing convention.
2. **`page_id` auto-fills with no backend change** — the per-tenant Facebook page is read from the
   existing `GET /api/integrations/messenger/pages` and auto-filled into the rule payload.

## What shipped

- **`nexus-ui/src/hooks/useFacebookAutomations.js`** — data hook (plain useState/useEffect, no React
  Query). Base path `/tenants/${activeTenantId}/facebook/automations`; `cacheVersion` in deps for
  workspace-switch refetch; `X-Tenant-ID` + `Authorization` auto-injected by `apiFetch`. Exposes
  `{ automations, pages, loading, error, busyId, refresh, createAutomation, updateAutomation,
  toggleActive, deleteAutomation }`.
- **`FacebookAutomationsPanel.jsx`** — glass-card section under `MessengerPanel` on `/integrations`;
  empty-state CTA when no page bound; owns modal open/edit state.
- **`AutomationTable.jsx`** — native table, match-type badge, Switch toggle, edit/delete with two-step
  confirm + per-row busy.
- **`AutomationBuilderModal.jsx`** — hand-rolled modal via `createPortal` (backdrop-filter on the glass
  shell traps `fixed` children → portal to `document.body`); create + edit; client validation gates Save
  on non-empty `trigger_keyword` and `reply_payload.message`.
- **Mount:** `IntegrationsPage.jsx`. **i18n:** `automations.*` block in `integrations.json` (en
  authoritative + 6 locale mirrors).

## Durable gotchas (captured to memory)

- `vite.config` hardcodes the prod proxy target (ignores `VITE_API_TARGET`).
- Glass-panel `backdrop-filter` creates a containing block that traps `position: fixed` → modals must
  `createPortal` to `document.body`.
- The dev-server tmux hook over-matches `npm run dev`.
- `deploy-rag.sh` ships the working tree (not git HEAD) and runs `alembic upgrade head`.

## Out of scope (deferred)
- Backend changes (CRUD API + `messenger/pages` already existed).
- Page binding/connect UI; LLM-triage fallback config; analytics; bulk ops; pagination.
- Visual flow builder — superseded by **Phase 58 (NEXUS Flow)**.
