# Frontend

The NEXUS frontend (`nexus-ui/`) is a React 18 SPA built with Vite, Tailwind CSS, and Radix UI primitives. It serves the chat interface, workspace settings, and admin tooling.

---

## Stack

| Layer | Technology |
|---|---|
| Framework | React 18 |
| Build tool | Vite |
| Styling | Tailwind CSS v3 |
| Components | Radix UI primitives |
| Routing | React Router v6 |
| State | React Context + hooks |
| Charts | Recharts |
| Icons | Lucide React |
| HTTP | Fetch API + custom `api.js` client |

---

## Design Language

Glassmorphic liquid glass design system — frosted glass panels, translucent rails, 3D depth backgrounds.

Key CSS tokens:

| Token | Description |
|---|---|
| `glass-rail` | Sidebar rail — frosted glass, 60% opacity backdrop blur |
| `glass-card` | Content cards — lighter frost, subtle border |
| `glass-pane` | Modals and overlays — heavy blur, dark tint |
| `glass-input` | Form inputs — semi-transparent with inset shadow |

---

## Page Map

| Route | Page | Auth required |
|---|---|---|
| `/` | Landing / login redirect | No |
| `/login` | Login form | No |
| `/chat` | Main chat interface | Yes |
| `/conversations` | Conversation history | Yes |
| `/documents` | Document library | Yes |
| `/products` | Product catalog | Yes |
| `/settings` | Account settings | Yes |
| `/settings/workspaces` | Workspace list | Yes |
| `/settings/workspaces/:slug` | Workspace detail (General/Members/Usage/Advanced/AI) | Yes (admin+) |
| `/settings/workspaces/:slug/ai` | Prompt Studio | Yes (admin+) |
| `/whats-new` | SaaS capability showcase | Yes |
| `/join` | Workspace invite accept | No (token-gated) |
| `/graph` | Knowledge graph visualization | Yes |

---

## Dev Setup

```bash
cd nexus-ui
npm install
npm run dev     # Vite dev server at http://localhost:5173
```

API requests proxy to `http://localhost:8501` via Vite config.

Build for production:

```bash
npm run build   # Output to nexus-ui/dist/
```

---

## Section Contents

| Doc | Description |
|---|---|
| [Pages & Routing](pages-and-routing.md) | All routes, navigation map, route guards |
| [Chat Interface](chat-interface.md) | SSE streaming, file uploads, citation rendering |
| [Workspace Settings UI](workspace-settings-ui.md) | Settings tabs: General / Members / Usage / Advanced / AI |
| [Graph Visualization](graph-visualization.md) | Phase 43: RelationGraph, node detail panel |
| [Command Palette](command-palette.md) | Phase 42: Cmd+K, keyboard shortcuts |
| [Design System](design-system.md) | Glass tokens, color palette, component conventions |
| [Dark Mode](dark-mode.md) | ThemeProvider, light/dark/system, localStorage |
| [AI Studio UI](ai-studio-ui.md) | Prompt Studio tabs, form validation |
| [Component Architecture](component-architecture.md) | Providers, hooks, nav.js DRY pattern |

---

## Related Docs

- [AI Customization — Prompt Studio](../06-ai-customization/prompt-studio.md)
- [API Reference](../03-api-reference/README.md) — endpoints the frontend calls
- [Workspace Management](../04-workspace-management/README.md)
