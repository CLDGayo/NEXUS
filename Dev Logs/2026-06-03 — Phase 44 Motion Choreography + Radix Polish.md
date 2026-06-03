# Phase 44 — Motion Choreography + Radix Polish

**Date:** 2026-06-03
**Owner:** Clarence Lloyd Gayo
**Version shipped:** `0.16.0`

## Context

The final phase of the `nexus-ui` UI/UX Modernization umbrella program. Phase 41 built the glass design tokens + GSAP motion hooks (`usePageMountTimeline`, `useTactilePress`, `useGsapContext`) but left them unwired. Phase 42 shipped the glass shell + Cmd+K palette. Phase 43 shipped the relation graph engine. Phase 44 wires the motion hooks into the pages and controls, and upgrades the two hand-rolled dropdowns to Radix — turning the app from a static dashboard into a kinetic, premium SaaS surface.

UI-only. No backend changes. No new hook code — the Phase 41 hooks were already built; this phase is pure wiring (verified: they were imported nowhere before P44).

## Decisions Locked

| Question | Decision |
|---|---|
| Profile dropdown | The "user profile dropdown in the sidebar" did **not** exist (footer was a static profile `Link` + logout button). Decision: **build a new** Radix dropdown-menu (Profile + Log out). |
| Tactile press scope | **Interactive elements only** — GraphViewSwitcher pills, IntegrationCard Connect, WorkspaceSwitcher trigger, PremiumConnectModal CTA. Display-only cards get the entrance cascade but NOT press feedback. |
| Tooltip provider | Single root `<Tooltip.Provider>` in `App.jsx`; Sidebar's local provider removed (root now covers nav tooltips too). |
| Integrations cascade granularity | **Panel level** (4 panels), not per-card — per-card would nest a `gsap.from` transform inside the grid panel's own transform = jank. |
| Dashboard cascade | Mark only the always-present header. KPI/Health/Activity/chart blocks load async (after the mount timeline runs), so marking them animates nothing on first paint. |

## What Was Built

### 2a. Page-mount choreography
`usePageMountTimeline()` ref attached to each page root; `data-animate` on cascade children.
- `GraphPage.jsx` — root + switcher wrapper.
- `DashboardPage.jsx` — root + header block.
- `WhatsNewPage.jsx` — root + header + each Capability/Roadmap card (wrapped in `data-animate` divs; grid `stretch` preserves equal heights).
- `IntegrationsPage.jsx` — root + each of the 4 panels wrapped in `data-animate` divs.

### 2b. Tactile micro-interactions
`useTactilePress()` on:
- `GraphViewSwitcher.jsx` — extracted a `GraphViewPill` sub-component so the hook gets **one ref per button** (hooks can't run in a `.map()`). Pills switched `transition-all` → `transition-colors` so CSS doesn't fight GSAP over `transform`.
- `IntegrationCard.jsx` — Connect button (hook called unconditionally for stable order; ref no-ops on connected cards).
- `PremiumConnectModal.jsx` — "Got it" CTA (hook before the early `return null`).
- `WorkspaceSwitcher.jsx` — the Radix trigger.

### 2c. Radix refactors
- `Sidebar.jsx` — new `@radix-ui/react-dropdown-menu` profile menu (avatar/name trigger → Profile + Log out), `glass-pane` content, collapsed/expanded layouts preserved. Local `Tooltip.Provider` removed.
- `WorkspaceSwitcher.jsx` — full rewrite from `useState`+click-outside to Radix dropdown-menu; `glass-pane` content; tenant list + owner Manage link preserved; `setActiveTenant` behavior unchanged.
- `PageHeader.jsx` — `@radix-ui/react-tooltip` `IconTooltip` wrapper on the hamburger + mobile Cmd+K (desktop Cmd+K keeps its visible label → no tooltip).
- `App.jsx` — root `<Tooltip.Provider delayDuration={0}>` wrapping the routes.

### Key lifecycle fix
`PremiumIntegrationsGrid.jsx` — the modal was always-mounted (returning `null` when closed), so its CTA was never in the DOM when `useTactilePress`'s mount effect ran → ref never wired. Switched to **conditional mount** (`{modalConnector !== null && <PremiumConnectModal open … />}`).

## Verification

**Gates:** `npm run build` ✓ (3534 modules, 3.19s; graph chunk `GraphPage-*.js` stays code-split at 191.83 kB / 61.45 kB gzip, out of the main index bundle). `npm run lint` ✓ — 3 errors / 7 warnings, all pre-existing in untouched files; **zero new**.

**Live Playwright smoke** (dev server → prod API, authed):
- Sidebar profile dropdown — Radix menu, Profile + Log out. ✓
- WorkspaceSwitcher — Radix glass menu, 3 tenants + owner Manage link. ✓
- Header tooltip — Radix `tooltip "Toggle sidebar"` on hover. ✓
- `/whats-new` cascade — 9 `data-animate` elements, **0 stuck at opacity:0**, transforms reset to identity. ✓
- `/integrations` — 4 panel cascade, 0 stuck; Connect → modal mounts with CTA (opacity 1). ✓
- `/graph` — lazy chunk loaded, canvas 2940×1520 (zero-width guard held), pill click → Ecosystem active. ✓
- 0 console errors across all pages (only first-load `favicon.ico` 404).

## Files Touched (12)

`src/App.jsx`, `src/components/layout/{Sidebar,PageHeader}.jsx`, `src/components/tenant/WorkspaceSwitcher.jsx`, `src/components/graph/GraphViewSwitcher.jsx`, `src/components/integrations/{IntegrationCard,PremiumConnectModal,PremiumIntegrationsGrid}.jsx`, `src/pages/{GraphPage,DashboardPage,WhatsNewPage,IntegrationsPage}.jsx`.

Reused unchanged: `src/hooks/{usePageMountTimeline,useTactilePress,useGsapContext}.js`, `src/lib/gsap.js`, `.glass-*` classes in `src/index.css`.

## Outcome

UI/UX Modernization umbrella program **complete** (P41 tokens/hooks → P42 shell/palette → P43 graph → P44 motion/Radix). Commits: P43 `38017c4`, P44 `fa5d011`.
