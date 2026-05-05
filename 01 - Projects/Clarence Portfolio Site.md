---
title: Clarence Portfolio Site
tags: [project, web, portfolio, active]
status: active
created: 2026-05-05
---

# Clarence Portfolio Site

Personal portfolio website for Clarence Lloyd Gayo, live at **https://clarence.gayo-sphere.cloud**.

## Stack

- **Framework:** Next.js / React (TypeScript)
- **Animations:** GSAP + ScrollTrigger
- **Styling:** Tailwind CSS + custom CSS vars in `src/index.css`
- **Theme:** next-themes (`dark` class on `<html>`)
- **Hosting:** VPS at `72.62.196.231` via [[Entities/GayoWordpress-VPS]]
- **Repo path:** `/Users/clarencelloydgayo/Gayo Sphere/Portfolio/GayoWordpress-VPS`

## Status

Active development — iterating on UI, theme support, and section polish.

## Key Decisions

- **CSS custom properties for all theme-sensitive colors** — components use `var(--token)` instead of hardcoded hex values. Light and dark values defined in `:root` and `.dark` inside `@layer base` in `src/index.css`. Adopted after hardcoded dark-mode inline styles made cards invisible in light mode.
- **Puppeteer opacity-force workaround for GSAP verification** — GSAP sets `opacity: 0` on cards before scroll triggers them. Puppeteer's synthetic scroll doesn't fire ScrollTrigger. Workaround: `document.querySelectorAll('[style*="opacity: 0"]').forEach(el => el.style.opacity = '1')` before screenshotting. Production behavior is correct.

## Recent Activity

- **2026-05-05** — Fixed text visibility across light/dark modes; fixed "What I Offer" service cards for light mode; shrunk cards to fit 2×2 in viewport. See [[Dev Logs/2026-05-05 — Clarence Portfolio Site]].

## Sections

| Section | Component | Notes |
|---------|-----------|-------|
| Hero | `Hero.jsx` | GSAP entrance animation |
| Services | `Services.tsx` | 2×2 grid, GSAP ScrollTrigger cards |
| Art | `Art.jsx` | — |
| Contact | — | — |
