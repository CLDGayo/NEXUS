---
content_hash: 503683e8efd580c9f18e67b8833add5aeb5e6cdb75d0ff48e6788a903c73e7bb
date: '2026-05-09'
date_ingested: '2026-05-09'
source: Claude.md
tags:
- inbox
- upload
title: Claude
---

# Portfolio Redesign Project — CLAUDE.md

## Project Purpose

This workspace exists to redesign Clarence's portfolio website (`clarence.gayo-sphere.cloud`) by prompting Claude Code with a **reference URL or screenshot image**. Claude will analyze the design and apply it to the existing React codebase.

The active portfolio codebase lives in `clarencegayo-main/`. The `gwyneth-main/` folder is a secondary reference portfolio that shares the same stack.

---

## Tech Stack

| Tool | Version | Notes |
|---|---|---|
| React | 18 | Component-based UI |
| TypeScript | 5 | Strict typing |
| Vite | 5 | Build tool |
| Tailwind CSS | 3 | Utility-first styling |
| shadcn/ui | latest | Radix-based component library |
| Framer Motion | 12 | Animations |
| react-router-dom | 6 | Routing |
| next-themes | 0.3 | Dark/light mode |
| Package manager | bun (preferred) or npm | Use `bun` when available |

---

## Project Structure

```
Portfolio/
├── CLAUDE.md                   ← This file
├── clarencegayo-main/          ← ACTIVE codebase (edit this)
│   ├── src/
│   │   ├── pages/
│   │   │   └── Index.tsx       ← Main page, assembles all sections
│   │   ├── components/         ← One file per section
│   │   │   ├── Navbar.tsx
│   │   │   ├── Hero.tsx
│   │   │   ├── Stats.tsx
│   │   │   ├── About.tsx
│   │   │   ├── Services.tsx
│   │   │   ├── Skills.tsx
│   │   │   ├── Training.tsx
│   │   │   ├── Experience.tsx
│   │   │   ├── Portfolio.tsx
│   │   │   ├── Testimonials.tsx
│   │   │   ├── Contact.tsx
│   │   │   ├── Footer.tsx
│   │   │   ├── LiquidBackground.tsx  ← Animated background blob
│   │   │   ├── AnimatedSection.tsx   ← Scroll-triggered wrapper
│   │   │   ├── BackToTop.tsx
│   │   │   ├── PageLoader.tsx
│   │   │   └── ui/             ← shadcn/ui primitives (avoid editing)
│   │   ├── index.css           ← CSS variables, design tokens, utilities
│   │   └── App.tsx             ← Providers + routing
│   ├── tailwind.config.ts      ← Tailwind theme + custom tokens
│   └── public/                 ← Static assets
└── gwyneth-main/               ← Reference portfolio (same stack)
```

---

## Dev Commands

Run from inside `clarencegayo-main/`:

```bash
bun dev          # Start dev server (http://localhost:8080)
bun build        # Production build → dist/
bun run preview  # Preview production build
```

---

## Redesign Workflow

When the user provides a **reference URL or image**, follow this process:

### 1. Analyze the Reference Design
- Identify: color palette, typography, layout structure, spacing, border-radius style, animation style, dark/light preference
- Note: navigation style, hero layout, card styles, section ordering, any unique UI patterns

### 2. Map Design to Codebase Layers

| What to change | Where |
|---|---|
| Colors, typography, spacing tokens | `src/index.css` (CSS variables) + `tailwind.config.ts` |
| Section layout & content | Individual component files in `src/components/` |
| Page section order | `src/pages/Index.tsx` |
| Fonts | `src/index.css` Google Fonts import + `tailwind.config.ts` fontFamily |
| Background effects | `LiquidBackground.tsx` |
| Animations | `AnimatedSection.tsx` + Framer Motion in individual components |

### 3. Apply Changes
- Update CSS variables in `index.css` first (colors, radius, shadows)
- Update `tailwind.config.ts` if new design tokens are needed
- Rewrite component markup and Tailwind classes to match the reference layout
- Preserve all existing **content** (name, bio, skills, projects, etc.) — only change the **design**
- Keep the neumorphic utility classes (`.neu-card`, `.neu-button`, `.neu-inset`) unless the new design explicitly replaces the shadow style

### 4. Preserve These Always
- All personal content (bio, skills list, project data, contact info, testimonials)
- Dark/light mode support via `next-themes`
- The `AnimatedSection` scroll-animation wrapper on each section
- React component structure and TypeScript types
- shadcn/ui primitives in `src/components/ui/` (do not rewrite these)

---

## Current Design System (Baseline)

### Colors (CSS vars in `index.css`)
- **Primary**: Teal `hsl(168 76% 42%)`
- **Secondary**: Coral/Orange `hsl(24 95% 53%)`
- **Background (light)**: Soft blue-gray `hsl(210 25% 96%)`
- **Background (dark)**: Deep navy `hsl(220 25% 10%)`

### Fonts
- **Body**: Outfit (Google Fonts)
- **Headings**: Space Grotesk (Google Fonts)

### Shadow Style
- Neumorphic (soft raised/inset shadows)
- Classes: `.neu-card`, `.neu-card-flat`, `.neu-inset`, `.neu-button`

### Section Order
Navbar → Hero → Stats → About → Services → Skills → Training → Experience → Portfolio → Testimonials → Contact → Footer

---

## Coding Conventions

- Use **Tailwind utility classes** for all styling; avoid inline styles unless animating with Framer Motion
- Use `cn()` from `@/lib/utils` for conditional class merging
- Use `@/` path alias for all imports (maps to `src/`)
- Component files are named `PascalCase.tsx`, one section per file
- Do not add new npm packages without asking first — prefer what is already installed
- Do not touch files in `src/components/ui/` unless explicitly asked
- Commit only when explicitly asked by the user

---

## How to Use This Project

1. Open `clarencegayo-main/` in the terminal and run `bun dev`
2. Provide Claude with a reference URL (e.g., a portfolio you admire) or a screenshot image
3. Claude will analyze the design and rewrite the relevant component files
4. Review the result in the browser at `http://localhost:8080`
5. Iterate by describing what to adjust
