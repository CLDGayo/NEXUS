# Graph Report - .  (2026-06-11)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 450 nodes · 745 edges · 33 communities (29 shown, 4 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e95d1e21`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 29|Community 29]]

## God Nodes (most connected - your core abstractions)
1. `api` - 30 edges
2. `useTenant()` - 25 edges
3. `cn()` - 17 edges
4. `useAuth()` - 17 edges
5. `usePageMountTimeline()` - 12 edges
6. `useTactilePress()` - 12 edges
7. `HTTPError` - 7 edges
8. `useSidebar()` - 6 edges
9. `clearToken()` - 6 edges
10. `scripts` - 5 edges

## Surprising Connections (you probably didn't know these)
- `nexus-ui` --references--> `Docker Compose Production`  [EXTRACTED]
  README.md → ../docker-compose.prod.yml
- `nexus-ui` --references--> `NEXUS System Summary`  [EXTRACTED]
  README.md → ../docs/nexus_system_summary.md
- `GraphViewPill()` --calls--> `useTactilePress()`  [EXTRACTED]
  src/components/graph/GraphViewSwitcher.jsx → src/hooks/useTactilePress.js
- `usePageMountTimeline()` --calls--> `DashboardPage()`  [EXTRACTED]
  src/hooks/usePageMountTimeline.js → src/pages/DashboardPage.jsx
- `usePageMountTimeline()` --calls--> `GraphPage()`  [EXTRACTED]
  src/hooks/usePageMountTimeline.js → src/pages/GraphPage.jsx

## Import Cycles
- None detected.

## Communities (33 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (20): NODES, TABS, LiquidBackground(), ORBS, useGsapContext(), usePageMountTimeline(), useTactilePress(), ICONS (+12 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (18): LiquidBackground, LoginScreen(), RequireAuth(), RequireSuperuser(), BackgroundBoundary, CommandPalette(), buildCommands(), useAuth() (+10 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (19): LEGEND_ITEMS, linkColor(), linkDirectionalParticleColor(), linkDirectionalParticles(), linkWidth(), nodeCanvasObject(), nodeColor(), GraphViewPill() (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (9): MD_COMPONENTS, TAG_STYLES, MD_COMPONENTS, STATUS_LABELS, METHOD_BADGE, STEPS, MD_COMPONENTS, MARKDOWN_PLUGINS (+1 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (5): ActivityPanel(), humanizeUptime(), fmt(), KpiCards(), DashboardPage()

### Community 5 - "Community 5"
Cohesion: 0.12
Nodes (13): createProduct(), deleteProduct(), deleteProductImage(), formatPrice(), getProduct(), listProducts(), reorderProductImages(), updateProduct() (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (15): SidebarContext, SidebarProvider(), useCommandPalette(), useHealthPoll(), useSidebar(), LiquidBackground, MATCHERS, resolveTitle() (+7 more)

### Community 7 - "Community 7"
Cohesion: 0.16
Nodes (14): WorkspaceDetailPage(), Button(), SIZES, VARIANTS, Card(), cn(), SegmentedControl(), Select() (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.14
Nodes (12): RequireManager(), RequireOwner(), RequireTenant(), useTenant(), JoinWorkspacePage(), SettingsWorkspacesPage(), WorkspacePickerModal(), WorkspaceSwitcher() (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (23): dependencies, @dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities, gsap, lucide-react, @radix-ui/react-dialog, @radix-ui/react-dropdown-menu (+15 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (21): description, devDependencies, autoprefixer, eslint, @eslint/js, eslint-plugin-react-hooks, eslint-plugin-react-refresh, globals (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.22
Nodes (11): LOGIN_ERROR_COPY, apiFetch(), getActiveTenantId(), setUnauthorizedHandler(), shouldInjectTenant(), TENANT_OPTIONAL_PATHS, authHeaders(), clearToken() (+3 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (7): AuthContext, AuthProvider(), TenantContext, TenantProvider(), setForbiddenTenantHandler(), setTenantIdProvider(), GraphPage

### Community 13 - "Community 13"
Cohesion: 0.14
Nodes (8): DocumentsTable(), PARA_FOLDERS, STATUS_PILL, useDebounced(), ALLOWED, formatBytes(), STATE_META, validate()

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (3): SCOPES, api, HTTPError

### Community 15 - "Community 15"
Cohesion: 0.22
Nodes (8): applyTheme(), systemPrefersDark(), ThemeContext, ThemeProvider(), VALID, useTheme(), OPTIONS, ThemeToggle()

### Community 16 - "Community 16"
Cohesion: 0.36
Nodes (3): ChatInterface(), newSessionId(), useChatStream()

### Community 18 - "Community 18"
Cohesion: 0.33
Nodes (6): Docker Compose Production, JWT Authentication, Legacy Vanilla-JS SPA, NEXUS System Summary, nexus-ui, SSE Streaming Layer

### Community 20 - "Community 20"
Cohesion: 0.60
Nodes (4): ALLOWED_MIME, AvatarUploader(), initialFor(), settingsHint()

### Community 22 - "Community 22"
Cohesion: 0.67
Nodes (3): formatTime(), LEVEL_STYLES, LogEntry()

## Knowledge Gaps
- **90 isolated node(s):** `name`, `private`, `version`, `type`, `description` (+85 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `api` connect `Community 14` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 8`, `Community 11`, `Community 12`, `Community 13`, `Community 17`, `Community 19`, `Community 20`, `Community 21`, `Community 24`, `Community 26`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Why does `usePageMountTimeline()` connect `Community 0` to `Community 2`, `Community 4`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `useTenant()` connect `Community 8` to `Community 1`, `Community 5`, `Community 14`, `Community 7`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **What connects `name`, `private`, `version` to the rest of the system?**
  _90 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.07439613526570048 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.08906882591093117 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.1053763440860215 - nodes in this community are weakly interconnected._