# Changelog

All notable changes to the NEXUS Knowledge Base.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-05-28

### Fixed
- **Products no longer stuck "Pending" in Documents.** Product Qdrant payload now carries `file`, `title`, `text`, `heading_path`, `folder`, `source_kind="product"` so `_qdrant_index_summary` aggregates product chunks and the Documents UI flips to "Indexed".
- **Chat citations show product names, not raw UUIDs.** Same payload enrichment lets the citation renderer label sources as e.g. `[1] Luffy Gear 4 Bound man` instead of the Qdrant point id, and gives the LLM real anchor text for product-related questions.
- **Messenger inbound dropped with `no_tenant_mapping`.** Operator-facing `seed_messenger_page` CLI binds a Facebook Page id to its owning tenant (idempotent, `ON CONFLICT DO UPDATE`). Inbound webhook now resolves Cozy Downloads Store events end-to-end.

### Added
- `rag/scripts/reupsert_products.py` — backfill the enriched product payload into Qdrant for existing rows; tenant-scoped via `--tenant`.
- `rag/scripts/seed_messenger_page.py` — bind `(facebook_page_id, tenant_slug)`; supports `--list-tenants` for discovery.
- `rag/tests/test_phase32_3_product_payload.py`, `rag/tests/test_phase32_3_reupsert_script.py`, `rag/tests/test_phase32_3_seed_messenger_page.py` — pin the payload contract and CLI surface.

### Changed
- `CLAUDE.md` Definition of Done now requires a CHANGELOG entry for any user-visible change. The What's New page is part of "done".

## [0.4.5] - 2026-05-28

### Added
- **Products surface in Documents view.** Phase 32.2 unions `app.documents` (vault notes) and `app.products` (catalogue) under a synthetic `/products/{slug}` folder so the SPA renders the full tenant artifact set.
- **Object-proxy token + presign serializer.** Image URLs in `/products` payloads are minted as 1-hour presigned MinIO GETs at serialization time when `MINIO_PUBLIC_BASE_URL` is unset, fixing broken-icon thumbnails in the carousel editor and product list.

### Fixed
- **Chat session "404 not found" on first send.** Backend now lazy-creates the `app.chat_sessions` row on the first `/api/chat/stream` POST instead of refusing client-minted UUIDs.
- **Image uploader hidden on new-product form.** Dropped the `isEditing` gate; the carousel now stages local blobs and flushes them to MinIO after `createProduct` resolves.

## [0.4.4] - 2026-05-28

### Fixed
- **Duplicated top nav on `/products` pages.** Removed page-level `PageHeader`; relocated affordances into inline toolbars and extended `AppShell.TITLES` with a regex fallback for `/products/:id`.
- **Broken-icon thumbnails in product list and carousel editor.** `_serialize_image` now `await`s a presigned URL whenever `public_url_for()` returns `None`. Parallel presigns batched with `asyncio.Semaphore(20)`.

## [0.4.3] - 2026-05-28

### Added
- **Phase 32 — Product Catalog + Meta Carousels.**
  - `app.products` + `app.product_images` (migration `0006`) with `(tenant_id, slug)` uniqueness, `price_cents >= 0`, `quantity >= 0` CHECK constraints.
  - `/api/products` CRUD, multipart image upload (Pillow → WebP, 1200px edge, configurable cap), drag-reorder with negative-offset swap, MinIO + Qdrant cleanup on delete.
  - `rag/products/sync.py` — deterministic `uuid5` point id, `upsert_product_to_qdrant` (embeds name + description with bge-small), idempotent delete.
  - Messenger product carousel via Meta Generic Template — `enrich_with_products_node` filters Qdrant by `kind=product+is_active=true+tenant_id`, JOINs Postgres for `quantity > 0` source-of-truth.
  - SPA `Products` page (owner-only) — search, grid, optimistic delete, edit form with image staging.

### Security
- Every product route gated by `require_owner` + tenant-scoped SQL filter. Cross-tenant rebind on `messenger/pages` returns 409.

## [0.4.2] - 2026-05-27

### Added
- **Phase 29.2 — Messenger ↔ Tenant binding.** `app.messenger_page_tenants` table (migration `0003`); inbound webhook now resolves owning tenant from `page_id` before scheduling the orchestrator run. Unmapped pages drop with structured `messenger.event.no_tenant_mapping` log; never default to a fallback tenant (closes the Phase 29 cross-tenant leak).
- Frontend tenant context injected via `X-Tenant-ID` header on every authenticated request.

## [0.4.1] - 2026-05-15

### Added
- **Phase 28.2 — Minio avatar uploads.** User avatars stored in tenant-scoped MinIO bucket; UI avatar picker with crop preview.
- **Dashboard tenancy fix.** KPIs now filter by `tenant_id` end-to-end; previously cross-tenant counts leaked into the Dashboard.

### Changed
- `mypy --strict` is now clean on the full `rag/` tree.

## [0.4.0] - 2026-05-15

### Added
- **Settings** page — user-tunable retrieval params (TOP_K, RETRIEVE_K, CHUNK_TOKENS, semantic/rerank thresholds), model picker (Groq + follow-up), theme toggle, password change, and JWT rotate.
- **What's New** page — sidebar entry with unread red-dot badge; renders this CHANGELOG.md.
- **Integrations** page — connect outbound webhooks (n8n/Make), Slack, Discord, and GitHub; subscribe to `ingest.*` and `chat.*` events; per-integration test-fire.
- **API tokens** — scoped Bearer tokens (`nxs_…`) for programmatic access to chat, documents, and dashboard endpoints. Plaintext shown once at creation.
- **Resources** page — prompt + template library backed by `<VAULT>/03 - Resources/prompts/`. Activate a prompt as the system prompt for chat; idempotent default-prompt seeding.
- **Event bus** (`rag/events.py`) — in-process async pub/sub feeding the integrations dispatcher. Events: `ingest.complete`, `ingest.failed`, `chat.complete`, `chat.feedback.up`, `chat.feedback.down`, `chat.error`.

### Changed
- `auth.py` + `deps.py` now read password + JWT secret from a filesystem overlay (`data/.password_override.json`) when set, falling back to env. Enables rotation without redeploy.
- `chat.py` reads `system_prompt_id`, `TOP_K`, `RERANK_CONFIDENCE_FLOOR`, and model names from the settings table at request time.

### Security
- Passwords stored as scrypt hash + per-installation salt in the overlay file (mode 600). Plaintext never persisted.
- API tokens stored as SHA-256 hashes; revocation is immediate (checked on every request, no cache).

## [0.3.0] - 2026-05-14

### Added
- Documents upload + archive endpoints with content-hash dedup and vector GC.
- Dashboard observability surface — KPIs, health pills, 7-day charts.
- Conversations history persistence (SQLite).

### Changed
- Migrated systemd unit from Chainlit to FastAPI/uvicorn (`app:app`).
- Mac dev connects to Qdrant via public HTTPS endpoint; no SSH tunnels.

## [0.2.0] - 2026-05-09

### Added
- Initial RAG pipeline — layout-aware Markdown chunking, fastembed (BAAI/bge-small-en-v1.5), Qdrant, Groq streaming.
- Single-password JWT auth + SPA shell (Dashboard, Documents, Chat, Conversations, Logs).
