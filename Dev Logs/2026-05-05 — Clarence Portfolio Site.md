---
title: "Dev Log: Clarence Portfolio Site — 2026-05-05"
tags: [dev-log, portfolio, css, gsap, theme]
project: "[[01 - Projects/Clarence Portfolio Site]]"
date: 2026-05-05
---

# Dev Log: Clarence Portfolio Site — 2026-05-05

## What Was Done

### 1. Fixed text visibility across light and dark modes

`src/index.css` had `section p { color: #ffffff !important; }` — this made paragraph text invisible on light backgrounds.

**Fix:**
- Added `--section-muted: #1a1a2e` to `:root` (light mode)
- Kept `--section-muted: #ffffff` in `.dark`
- Changed rule to `section p { color: var(--section-muted); }`

### 2. Fixed "What I Offer" service cards for light mode

`Services.tsx` had all inline styles hardcoded with dark-mode values (`rgba(255,255,255,0.04)` backgrounds, white text, white icon colors). Cards were invisible in light mode.

**Fix:** Introduced component-specific CSS vars in `src/index.css`:

| Token | Light | Dark |
|-------|-------|------|
| `--svc-card-bg` | `#ffffff` | `rgba(255,255,255,0.04)` |
| `--svc-card-border` | `rgba(0,0,0,0.10)` | `rgba(255,255,255,0.09)` |
| `--svc-card-heading` | `#0f172a` | `hsl(var(--primary))` |
| `--svc-icon-color` | `hsl(var(--primary))` | `#ffffff` |
| `--svc-item-color` | `#334155` | `rgba(255,255,255,0.78)` |
| `--svc-bullet-border` | `rgba(0,0,0,0.25)` | `rgba(255,255,255,0.35)` |
| `--svc-btn-bg` | `rgba(124,58,237,0.08)` | `rgba(0,0,0,0.55)` |
| `--svc-btn-color` | `hsl(var(--primary))` | `#ffffff` |

All `Services.tsx` inline style values replaced with `var(--svc-*)`.

### 3. Shrunk service cards to fit 2×2 in viewport

Reduced padding, font sizes, and margins so all 4 cards fit within a ~900px viewport height. Card height target: ~350px each.

## Files Changed

- `src/index.css` — CSS vars, paragraph color fix
- `src/components/Services.tsx` — inline styles → CSS vars, size reductions

## Pending

- Update `GayoWordpress-VPS/CLAUDE.md` to add rule: all screenshots must save to `./temporary screenshots/` folder.

## Patterns Learned

- [[Concepts/Theme-Aware CSS Variables]] — CSS vars in `:root`/`.dark` for any component that needs light/dark color variants; use `var(--token)` in inline styles so next-themes dark class propagates correctly.
- [[Concepts/GSAP Puppeteer Verification Workaround]] — Force `opacity: 1` on `[style*="opacity: 0"]` elements before screenshotting; real browser scroll triggers GSAP correctly.
