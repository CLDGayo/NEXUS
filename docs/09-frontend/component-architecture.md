# Component Architecture

Structure of the React component tree, context providers, custom hooks, and the `nav.js` DRY navigation pattern.

---

## Provider Stack

Providers wrap the entire app in order (outer → inner):

```
<ThemeProvider>          — dark/light/system mode
  <AuthProvider>         — JWT token, user object, login/logout
    <TenantProvider>     — current workspace, tenant list
      <ChatProvider>     — active conversation, message history
        <Router>
          <App />
        </Router>
      </ChatProvider>
    </TenantProvider>
  </AuthProvider>
</ThemeProvider>
```

Each provider exposes a hook:

| Provider | Hook | Key values |
|---|---|---|
| `ThemeProvider` | `useTheme()` | `theme`, `setTheme` |
| `AuthProvider` | `useAuth()` | `user`, `token`, `login()`, `logout()` |
| `TenantProvider` | `useTenant()` | `currentTenant`, `tenants`, `switchTenant()` |
| `ChatProvider` | `useChat()` | `messages`, `sendMessage()`, `streamState` |

> **📝 NOTE:** `*Provider.jsx` files trigger a `react-refresh` warning in the Vite dev console — this is intentional and pre-existing. Do not suppress or "fix" it; the warning does not affect functionality.

---

## `api.js` — HTTP Client

All API calls go through `nexus-ui/src/lib/api.js`:

```javascript
import { HTTPError } from './errors';

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('nexus_token');
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      'Authorization': token ? `Bearer ${token}` : '',
      'Content-Type': 'application/json',
      ...options.headers,
    }
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new HTTPError(res.status, body);
  }
  return res.json();
}
```

**`HTTPError`** — always access error details via `.body` not `.message`:

```javascript
try {
  await apiFetch('/tenants/123/members', { method: 'DELETE' });
} catch (e) {
  if (e instanceof HTTPError) {
    console.error(e.body.detail);  // ✅ correct
    console.error(e.message);      // ❌ generic — not useful
  }
}
```

---

## `nav.js` — DRY Navigation

`nexus-ui/src/lib/nav.js` exports all route constants and navigation helpers. Every component imports routes from here — no hardcoded strings:

```javascript
export const ROUTES = {
  CHAT: '/chat',
  CONVERSATIONS: '/conversations',
  DOCUMENTS: '/documents',
  SETTINGS: '/settings',
  WORKSPACE: (slug) => `/settings/workspaces/${slug}`,
  WORKSPACE_AI: (slug) => `/settings/workspaces/${slug}/ai`,
  JOIN: (token) => `/join?token=${token}`,
};
```

Usage:

```javascript
import { ROUTES } from '../lib/nav';
navigate(ROUTES.WORKSPACE(tenant.slug));
```

---

## Directory Structure

```
nexus-ui/src/
  components/
    chat/            ChatWindow, MessageBubble, SourcePanel, FollowUpChips
    workspace/       WorkspaceSettings, MembersTab, UsageTab, AITab
    ui/              Button, Input, Modal, Tabs (Radix wrappers)
    layout/          Sidebar, TopBar, CommandPalette, AppBackground
  pages/             Route-level components (one per page)
  providers/         AuthProvider, TenantProvider, ChatProvider, ThemeProvider
  hooks/             useStream, useDebounce, useKeyboard, useLocalStorage
  lib/               api.js, nav.js, errors.js, utils.js
  styles/            glass.css, animations.css
```

---

## Pre-Existing Lint Errors

Three lint errors exist in the codebase and are known/non-blocking:

1. `react-refresh` warning in `*Provider.jsx` files — intentional, do not fix
2. Two other pre-existing warnings in legacy components

Do not introduce new lint errors. Do not attempt to silence the existing ones.

---

## Related Docs

- [Design System](design-system.md)
- [Dark Mode](dark-mode.md)
- [Chat Interface](chat-interface.md)
