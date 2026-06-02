# Phase 42 — Glass Shell + Command Palette

**Date:** 2026-06-02
**Owner:** Clarence Lloyd Gayo
**Version shipped:** `0.14.0`

## Context

Phase 41 shipped the glass design token layer (Tailwind tokens, `@layer components` glass classes, GSAP foundation hooks) as a no-visual-change foundation. Phase 42 activates all of it: the NEXUS shell now renders as a frosted-glass SaaS interface with a Cmd+K command palette and a collapsible, localStorage-persisted sidebar.

This phase is UI-only. No backend changes, no new routes, no TypeScript, no new npm dependencies.

## Decisions Locked

| Question | Decision |
|---|---|
| How to share nav data between Sidebar and palette? | Extract to `src/lib/nav.js` pure-data module. react-refresh/only-export-components flags non-component exports in `.jsx`; a plain `.js` file is clean. |
| Sidebar state location? | `SidebarProvider` context, mirroring `AuthProvider`/`TenantProvider` idiom. Keeps `AppShell` thin. |
| Where does the Cmd+K listener live? | `useCommandPalette` hook — owns both `open` state and the `window.keydown` listener. StrictMode-safe (symmetric add/remove). |
| Command palette dialog primitive? | `@radix-ui/react-dialog` (already installed Phase 41). Radix handles focus-trap, Esc, scroll-lock, overlay-click — we own search, filter, keyboard nav, and run logic. |
| How does AppShell avoid `/graph` title? | TITLES map unchanged. No `/graph` entry. Deferred to Phase 43 per plan. |
| SidebarProvider inside or outside `useLocation`? | Inside — `ShellInner` calls `useLocation` while wrapped by `SidebarProvider`; `AppShell` is the thin wrapper that provides context. |

## What Was Built

### New files

**`src/lib/nav.js`**
Pure data module. Exports `CORE_NAV`, `OWNER_NAV`, `TRAILING_NAV`, `ADMIN_NAV_ITEM` verbatim from the former `Sidebar.jsx` inline definitions, with their lucide-react icon imports. Single source of truth for both sidebar and command palette.

**`src/context/SidebarProvider.jsx`**
Mirrors `AuthProvider.jsx`. `SidebarContext = createContext(null)`. `SidebarProvider` lazy-initializes `collapsed` from `localStorage`, persists on change via `useEffect`, stabilizes `toggle` with `useCallback`, and memoizes `{ collapsed, toggle, setCollapsed }`.

**`src/hooks/useSidebar.js`**
Guarded `useContext(SidebarContext)` — throws `'useSidebar must be used inside <SidebarProvider>'` when context is null. Matches `useAuth.js` / `useTenant.js` shape exactly.

**`src/hooks/useCommandPalette.js`**
`useState(false)` + `useEffect` that registers/removes a `keydown` listener. `(e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'` → `e.preventDefault()` + toggle. Returns `{ open, setOpen }`.

**`src/components/command/commands.js`**
`buildCommands({ isOwner, isSuperuser })` — derives nav commands from `nav.js` arrays (role-gated), appends one `{ id:'logout', kind:'action' }` command. No `/graph` entry.

**`src/components/command/CommandPalette.jsx`**
Radix `Dialog.Root/Portal/Overlay/Content`. `Dialog.Title` with `sr-only` for a11y. Autofocused `<input>` (via `onOpenAutoFocus` override). State: `query`, `activeIndex`. Case-insensitive filter. ArrowDown/ArrowUp (clamped) + Enter keyboard nav. `activeIndex` resets on `query` change and on `open` toggle. Nav commands: `navigate(cmd.to)` + close. Action commands: `logout()` + close. Empty-state row. Mouse hover sets `activeIndex`. Styled: `glass-overlay` + `glass-dialog`, `fixed left-1/2 top-24 z-50 max-w-lg -translate-x-1/2`.

### Modified files

**`src/components/layout/Sidebar.jsx`**
- Nav arrays imported from `../../lib/nav.js`; inline definitions removed.
- `useSidebar()` drives `collapsed`.
- `<aside>`: `glass-rail flex flex-col shrink-0 transition-[width] duration-300` + `w-16`/`w-60`.
- Header: collapsed = centered "N" glyph; expanded = "NEXUS / Knowledge Base".
- Nav wrapped in `<Tooltip.Provider delayDuration={0}>`. Collapsed = icon-only + right-side `glass-pane` tooltip; expanded = icon + label.
- Footer: collapsed = stacked avatar + logout icon; expanded = avatar/name/role + logout.
- `Avatar` extracted as a local helper component (handles profile image URL vs. initial fallback).

**`src/components/layout/PageHeader.jsx`**
- Signature: `PageHeader({ title, right, onOpenCommand })`.
- `<header>`: `glass-header sticky top-0 z-20`.
- Left: `PanelLeft` hamburger → `useSidebar().toggle` + title `<h1>`.
- Right: pill Cmd+K trigger (desktop, `hidden sm:flex`) + icon-only trigger (mobile, `flex sm:hidden`) + `{right}` + `<WorkspaceSwitcher/>` + `<HealthBadge/>`.

**`src/components/layout/AppShell.jsx`**
- Refactored to `AppShell` (thin wrapper providing `<SidebarProvider>`) + `ShellInner` (calls hooks, renders shell).
- Ambient gradient: `absolute inset-0 -z-10 bg-gradient-to-br from-blue-100/50 via-slate-50 to-violet-100/40`.
- `useCommandPalette()` inside `ShellInner`; `<CommandPalette>` mounted as last child.
- `<PageHeader onOpenCommand={() => setOpen(true)} />`.
- `<main>` and `flex-1 min-h-0 overflow-hidden` Outlet wrapper unchanged.

## Verification

- `npm run build` — green. 2634 modules, no Vite errors. Pre-existing chunk-size warning (>500 kB) unchanged.
- `npm run lint` — 10 problems, all pre-existing (AuthProvider.jsx error, api.js error, vite.config.js error, DocumentsTable.jsx warnings, IntegrationCard.jsx warning, TenantProvider.jsx warning). New files: zero errors, one expected `react-refresh/only-export-components` warning in `SidebarProvider.jsx` (same pattern as AuthProvider.jsx and TenantProvider.jsx — established project idiom for context providers).
- Manual dev verification deferred to orchestrator/user (per spec, `npm run dev` not started by execute-agent).

## Constraints Respected

- Plain JSX only. No TypeScript, no new npm deps.
- No `/graph` route, no Phase 43 topology work.
- No GSAP wiring or WorkspaceSwitcher refactor (Phase 44).
- No backend changes.
- StrictMode-safe: `useCommandPalette` uses symmetric `addEventListener`/`removeEventListener`; `SidebarProvider` uses `useCallback` for stable `toggle`.
