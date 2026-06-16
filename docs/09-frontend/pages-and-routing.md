# Pages and Routing

nexus-ui uses React Router v6. All routes are defined in `nexus-ui/src/nav.js` as `ROUTES` constants.

---

## Route Map

| Path | Page component | Auth required | Role required |
|---|---|---|---|
| `/` | `HomePage` | No | — |
| `/login` | `LoginPage` | No | — |
| `/register` | `RegisterPage` | No | — |
| `/join` | `JoinWorkspacePage` | No | — |
| `/chat` | `ChatPage` | Yes | any |
| `/chat/:threadId` | `ChatPage` | Yes | any |
| `/documents` | `DocumentsPage` | Yes | any |
| `/documents/upload` | `DocumentUploadPage` | Yes | admin/owner |
| `/products` | `ProductsPage` | Yes | any |
| `/products/new` | `ProductFormPage` | Yes | admin/owner |
| `/products/:id/edit` | `ProductFormPage` | Yes | admin/owner |
| `/whats-new` | `WhatsNewPage` | No | — |
| `/settings` | Redirect → `/settings/workspaces` | Yes | any |
| `/settings/workspaces` | `WorkspaceListPage` | Yes | any |
| `/settings/workspaces/:slug` | `WorkspaceSettingsPage` | Yes | any |
| `/settings/profile` | `ProfilePage` | Yes | any |
| `/settings/tokens` | `ApiTokensPage` | Yes | any |
| `/admin` | `AdminDashboardPage` | Yes | admin/owner |
| `/admin/settings` | `SystemSettingsPage` | Yes | owner |
| `*` | `NotFoundPage` | No | — |

---

## Auth Guard

Routes with `auth required` use the `<ProtectedRoute>` component, which:

1. Reads `AuthContext.user`
2. If `null`, redirects to `/login?next={current_path}`
3. After login, redirects back to `next`

Role-gated routes additionally check `AuthContext.role` against the required minimum role (member < admin < owner). Insufficient role → `403` page rendered in-place, not redirect.

---

## Navigation Structure

```
nexus-ui/src/nav.js
```

`ROUTES` object — single source of truth for all paths:

```javascript
export const ROUTES = {
  HOME: '/',
  LOGIN: '/login',
  CHAT: '/chat',
  CHAT_THREAD: '/chat/:threadId',
  DOCUMENTS: '/documents',
  PRODUCTS: '/products',
  WHATS_NEW: '/whats-new',
  WORKSPACE_SETTINGS: '/settings/workspaces/:slug',
  ADMIN: '/admin',
  // ...
};
```

Import `ROUTES` everywhere — never hardcode path strings.

---

## Sidebar Navigation

The left sidebar (`SidebarNav`) renders links from `ROUTES`, filtered by:

1. Auth state (unauthenticated users see Home/Login only)
2. Role (Admin Dashboard hidden from `member`)
3. Active workspace (items disabled when workspace is archived)

---

## Join Flow (`/join`)

`/join?token=abc123` is the invite acceptance page:

1. Parse `token` from query string
2. `GET /api/invites/preview?token=abc` to show workspace name + inviter
3. If user not logged in → redirect to `/login?next=/join?token=abc`
4. On confirm → `POST /api/invites/accept` with token
5. On success → redirect to `/settings/workspaces/{slug}`

---

## Related Docs

- [Component Architecture](component-architecture.md)
- [Token-Based Invites](../04-workspace-management/token-based-invites.md)
- [Workspace Settings UI](workspace-settings-ui.md)
