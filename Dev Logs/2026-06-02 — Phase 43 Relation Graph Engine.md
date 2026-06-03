# Phase 43 — Relation Graph Engine

**Date:** 2026-06-02
**Owner:** Clarence Lloyd Gayo
**Version shipped:** `0.15.0`

## Context

Phase 42 shipped the glassmorphic shell and Cmd+K palette, deliberately deferring the `/graph` route and force-graph engine. Phase 43 delivers the third pillar of the UI/UX Modernization umbrella: an interactive, physics-based force-directed graph at `/graph` that visualises NEXUS's real backend topology across three swappable views.

This phase is UI-only. No backend changes. Topology data is curated static client code mirroring the real backend (`rag/orchestrator/graph.py`, `rag/messenger/`, `rag/retrieval/`).

## Decisions Locked

| Question | Decision |
|---|---|
| Graph library | `react-force-graph-2d` (HTML5 Canvas + d3-force). 2D-only variant — no three.js weight. |
| Graph data source | Static `src/lib/topology.js`. Three subgraphs from real backend node names. No endpoint. |
| Canvas ↔ Tailwind bridge | `GRAPH_COLORS` hex map in `topology.js`, mirrored from `tailwind.config.js colors.nexus.*`. |
| Code splitting | `React.lazy(() => import('./pages/GraphPage.jsx'))`. Rollup auto-splits on dynamic import — no `manualChunks` needed. Proven: separate `GraphPage-[hash].js` chunk (191.69 kB / 61.37 kB gzip). |
| Canvas sizing | `useGraphDimensions` ResizeObserver on the container div. Returns `width:0` until measured; `<ForceGraph2D>` not mounted until `width > 0`. Picks up sidebar collapse automatically (reflows flex main). |
| Node pinning | `onNodeDragEnd` sets `node.fx = node.x; node.fy = node.y`. Standard react-force-graph-2d pattern. |
| GlassSpinner | Net-new `src/components/graph/GlassSpinner.jsx` — co-located in `graph/` as it only backs the lazy route's Suspense fallback. |
| Cmd+K auto-populate | `buildCommands()` already derives nav commands from `CORE_NAV`. Adding `/graph` to `CORE_NAV` in `nav.js` was sufficient — no functional change to `commands.js`. |

## What Was Built

### New files (10)

**`src/lib/topology.js`**
Static graph spine. `GRAPH_COLORS` hex bridge. Three subgraphs (`LANGGRAPH_RUNTIME` 20 nodes, `CONVERSION_LIFECYCLE` 12 nodes, `ECOSYSTEM` 8 nodes) using exact backend node names. Node `state ∈ {healthy,active,paused,abstain,stub}`. Edge `kind ∈ {normal,conditional,barrier,loop}`. `SUBGRAPHS` + `VIEW_META` registry exports.

**`src/components/graph/graphTheme.js`**
Canvas style functions: `nodeColor`, `nodeCanvasObject` (crisp circle + white-halo label at any zoom), `linkColor` (amber=conditional, violet=barrier, cyan=loop, slate=normal), `linkDirectionalParticles` (active-path only, 3 particles), `linkWidth`.

**`src/components/graph/useGraphDimensions.js`**
`ResizeObserver` hook → `{ width, height }`. Measures immediately on mount, disconnects in cleanup (StrictMode-safe). Returns `width:0` until first measurement.

**`src/components/graph/RelationGraph.jsx`**
`ForceGraph2D` wrapper. Owns `containerRef` + dimensions hook. Guards zero-width mount. Transparent background. Wires theme fns. Pins nodes on drag end.

**`src/components/graph/GraphViewSwitcher.jsx`**
Segmented glass pill: `LangGraph Runtime | Conversion Lifecycle | Ecosystem`. Controlled. Active segment accent-filled. Plain click handlers (GSAP wiring is Phase 44).

**`src/components/graph/GraphLegend.jsx`**
`glass-pane` state swatch legend (5 items). Bottom-left corner overlay. `pointer-events-none`.

**`src/components/graph/NodeDetailPanel.jsx`**
`glass-card` node detail: label, state badge, group, in/out edges with kind tags. Dismissible. Null-renders when no selection.

**`src/components/graph/GlassSpinner.jsx`**
`glass-pane` + `Loader2 animate-spin` Suspense fallback. Co-located with graph components.

**`src/pages/GraphPage.jsx`**
Workspace assembly. `h-full overflow-hidden`. Manages `activeView` (default `runtime`) + `selectedNode` state. Composes all graph sub-components.

### Modified files (3)

**`src/App.jsx`**
`lazy`/`Suspense` from `react`. `GlassSpinner` static import. `const GraphPage = lazy(...)` after all static imports. `/graph` route inside AppShell protected block, after `/resources`, not owner-gated, wrapped in `<Suspense fallback={<GlassSpinner/>}>`.

**`src/lib/nav.js`**
`Network` added to lucide-react import block. `{ to:'/graph', label:'Graph', Icon:Network }` appended to `CORE_NAV`. This single change also auto-populates the Cmd+K palette.

**`src/components/command/commands.js`**
Stale comment "No /graph command — that route lands in Phase 43" updated to accurate note.

## Verification

- `npm run build` — green. 3522 modules transformed.
  - `GraphPage-C_mW7AUG.js` — **191.69 kB** (61.37 kB gzip) — async chunk: react-force-graph-2d + d3-force isolated here.
  - `index--uEGveu3.js` — **1,019.01 kB** (303.30 kB gzip) — main bundle, no force-graph weight added vs P42 baseline.
  - The >500 kB warning on `index` is pre-existing (unchanged from P42).
- `npm run lint` — 10 problems, all pre-existing. Zero new errors or warnings from Phase 43 files.
- Manual dev verification deferred to orchestrator/user (per spec, `npm run dev` not started by execute-agent).

## Constraints Respected

- Plain JSX only. No TypeScript.
- `react-force-graph-2d` is the only new npm dependency.
- No backend changes. Topology is static client data.
- No Phase 44 work (GSAP page timelines, `useTactilePress` on switcher, WorkspaceSwitcher Radix refactor).
- Unrelated dirty paths (`.claude/hooks/.logs/hook-log.jsonl`, `_publish` submodule) left untouched and not staged.
- StrictMode-safe: `useGraphDimensions` disconnects observer in cleanup; no GSAP contexts introduced.
