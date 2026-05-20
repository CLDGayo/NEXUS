# nexus-ui

Phase 10 frontend for NEXUS. React + Vite + Tailwind. Replaces the
legacy vanilla-JS SPA at [`../rag/static/`](../rag/static/) once the
component port and SSE streaming layer ship in Steps 2 – 4.

See [../docs/nexus_system_summary.md](../docs/nexus_system_summary.md)
for the surrounding architecture.

## Dev

```bash
cd nexus-ui
npm install
npm run dev          # http://127.0.0.1:5173
```

`vite.config.js` proxies `/api` and `/webhook` to
`http://127.0.0.1:8210` (the host bind in
[`../docker-compose.prod.yml`](../docker-compose.prod.yml) for the v2
docker stack). Override with `VITE_API_TARGET` in `nexus-ui/.env.local`:

```bash
# .env.local
VITE_API_TARGET=http://127.0.0.1:8000   # base docker-compose.yml
```

The proxy disables gzip encoding on `/api` so SSE tokens stream without
buffering.

## Build

```bash
npm run build        # → dist/
npm run preview      # serve dist/ on 127.0.0.1:4173
```

## Status

This is **Step 1 only** — scaffold + dev proxy. The default route renders
a "Phase 10 scaffold OK" card. Components, routing, and SSE streaming
land in Step 2 – 3 (`src/components/`, `src/lib/sse.js`,
`src/hooks/useChatStream.js`).

The legacy SPA at `../rag/static/` is still the production frontend.
Nothing here is wired into FastAPI yet.

## Constraints (from the Phase 10 directive)

- Do not touch `../rag/static/` — live traffic.
- Do not touch `../rag/` Python — API contracts locked.
- Preserve the legacy contract: JWT in `localStorage` under
  `nexus_token`, `Authorization: Bearer <token>` on every authed
  request, SSE events shaped `{ type: 'status' | 'sources' | 'token' |
  'followups' | 'error', ... }` on `POST /api/chat/stream`.
