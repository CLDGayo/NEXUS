# Design System

NEXUS uses a glassmorphic liquid glass design language: frosted translucent panels, depth-layered backgrounds, and a pastel-forward color palette.

---

## Glass Tokens

Defined in `nexus-ui/src/styles/glass.css` and extended in `tailwind.config.js`:

| Token | CSS class | Visual effect |
|---|---|---|
| Rail | `glass-rail` | Sidebar/nav rail — 60% opacity, `backdrop-blur-xl`, subtle border |
| Card | `glass-card` | Content cards — lighter frost, `backdrop-blur-md`, inset shadow |
| Pane | `glass-pane` | Modals/overlays — heavy blur, dark tint |
| Input | `glass-input` | Form inputs — semi-transparent, inset shadow on focus |
| Button | `glass-btn` | Action buttons — frosted with hover brightness lift |

---

## Color Palette

| Name | Hex | Used for |
|---|---|---|
| `nexus-sky` | `#A8D8EA` | Primary accent, links, active states |
| `nexus-lavender` | `#B8A9E3` | Secondary accent, AI/settings surfaces |
| `nexus-blush` | `#F2B5C0` | Danger / warning states |
| `nexus-mint` | `#A8E6CF` | Success states |
| `nexus-sand` | `#F5E6C8` | Neutral warm surface |
| `glass-white` | `rgba(255,255,255,0.12)` | Base glass tint |
| `glass-border` | `rgba(255,255,255,0.18)` | Glass panel borders |

---

## 3D Background

The app background is a dynamic 3D gradient mesh — layered radial gradients animating slowly via CSS keyframes. Defined in `AppBackground.jsx`.

```css
/* Simplified — actual uses 6 gradient layers */
@keyframes mesh-drift {
  0%   { background-position: 0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
```

---

## Typography

| Scale | Tailwind class | Usage |
|---|---|---|
| Display | `text-4xl font-bold` | Page headers |
| Heading | `text-xl font-semibold` | Section headings |
| Body | `text-sm` | Default text |
| Caption | `text-xs text-muted` | Labels, timestamps |
| Mono | `font-mono text-xs` | Code, IDs, token counts |

Font stack: `Inter, system-ui, sans-serif` (body); `JetBrains Mono` (code).

---

## Component Conventions

### Radix UI Primitives

Radix provides unstyled accessible primitives — NEXUS adds glass styling on top:

```jsx
// Example: styled Radix Dialog
<Dialog.Root>
  <Dialog.Content className="glass-pane rounded-2xl p-6 shadow-xl">
    {children}
  </Dialog.Content>
</Dialog.Root>
```

Radix handles: focus trapping, keyboard navigation, ARIA attributes, portal rendering.

### Icon System

All icons use Lucide React at `size={16}` (small) or `size={20}` (standard):

```jsx
import { Settings, MessageSquare, ChevronRight } from 'lucide-react';
```

---

## Spacing Scale

NEXUS uses Tailwind's default spacing scale. Common patterns:

| Context | Padding |
|---|---|
| Card content | `p-4` (16px) |
| Modal | `p-6` (24px) |
| Sidebar item | `px-3 py-2` |
| Button | `px-4 py-2` |

---

## Dark Mode

See [Dark Mode](dark-mode.md). The glass tokens adapt automatically — dark mode increases blur and darkens the base tint.

---

## Related Docs

- [Dark Mode](dark-mode.md)
- [Component Architecture](component-architecture.md)
- [AI Studio UI](ai-studio-ui.md)
