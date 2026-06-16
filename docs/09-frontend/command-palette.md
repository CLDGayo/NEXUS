# Command Palette

Phase 42 feature. `Cmd+K` (Mac) / `Ctrl+K` (Windows) opens a global command palette for keyboard-driven navigation and actions.

---

## Activation

| Trigger | Action |
|---|---|
| `Cmd+K` | Open palette |
| `Esc` | Close palette |
| `↑` / `↓` | Navigate results |
| `Enter` | Execute selected command |

---

## Commands

Commands are role-gated — only commands the current user can execute are shown.

| Command | Role required | Action |
|---|---|---|
| New conversation | member+ | `navigate(ROUTES.CHAT)` + reset chat |
| Go to Documents | member+ | `navigate(ROUTES.DOCUMENTS)` |
| Go to Products | member+ | `navigate(ROUTES.PRODUCTS)` |
| Workspace settings | admin+ | `navigate(ROUTES.WORKSPACE(slug))` |
| Invite member | admin+ | Opens invite modal |
| AI Settings | admin+ | `navigate(ROUTES.WORKSPACE_AI(slug))` |
| Switch workspace | member+ (multi-tenant) | Tenant selector dropdown |
| Logout | any | `logout()` from `useAuth()` |

---

## Implementation

`CommandPalette.jsx` uses Radix `Dialog` + `cmdk` library for fuzzy search:

```jsx
import { Command } from 'cmdk';

<Command.Dialog open={open} onOpenChange={setOpen}>
  <Command.Input placeholder="Type a command..." />
  <Command.List>
    {roleGatedCommands.map(cmd => (
      <Command.Item key={cmd.id} onSelect={() => { cmd.action(); setOpen(false); }}>
        <cmd.icon size={16} />
        {cmd.label}
      </Command.Item>
    ))}
  </Command.List>
</Command.Dialog>
```

---

## Keyboard Hook

`useKeyboard.js` registers the global shortcut:

```javascript
useEffect(() => {
  const handler = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      setOpen(true);
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, []);
```

---

## Related Docs

- [Component Architecture](component-architecture.md)
- [Design System](design-system.md) — `glass-pane` styling for palette overlay
