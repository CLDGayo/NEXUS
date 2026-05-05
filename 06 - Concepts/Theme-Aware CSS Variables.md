---
title: Theme-Aware CSS Variables
tags: [concept, css, dark-mode, theming, frontend]
created: 2026-05-05
---

# Theme-Aware CSS Variables

A pattern for building components that respond correctly to both light and dark mode without duplicating component code.

## The Pattern

Define all color/background tokens as CSS custom properties in `@layer base`, with separate values for `:root` (light) and `.dark` (dark):

```css
@layer base {
  :root {
    --component-bg: #ffffff;
    --component-text: #1a1a2e;
  }
  .dark {
    --component-bg: rgba(255, 255, 255, 0.04);
    --component-text: #ffffff;
  }
}
```

Then use `var(--token)` in component styles — including inline styles in React/TSX:

```tsx
<div style={{ background: "var(--component-bg)", color: "var(--component-text)" }}>
```

## Why It Works with next-themes

next-themes applies a `dark` class to `<html>`. CSS var cascading means `.dark` overrides `:root` for all descendant elements. No JS required in components — just the CSS var reference.

## When to Use

- Any component with hardcoded light or dark hex values
- Before inlining any `rgba(255,255,255,...)` value in a component — ask: does this only work in one mode?
- When a component looks fine in dark mode but is invisible in light mode (or vice versa)

## Related

- [[Concepts/GSAP Puppeteer Verification Workaround]]
- [[01 - Projects/Clarence Portfolio Site]]
