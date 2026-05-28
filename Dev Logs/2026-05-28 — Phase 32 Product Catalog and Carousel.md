# Phase 32 — Product Catalog & Visual Webhook Routing

**Date:** 2026-05-28
**Owner:** Clarence Lloyd Gayo
**Architect directive:** Phase 32 — bring Nexus from RAG-only to E-Commerce AI.

## Summary

Shipped the structured Product Catalog (Postgres registry + MinIO image
store + Qdrant semantic index) and wired the existing Messenger webhook
to dispatch product carousels via Meta Generic Templates. Owner-gated
end to end (frontend route guard + backend `require_owner` dependency +
tenant_id filter on every SQL query).

## Changes (22 files)

**Backend**
- `rag/migrations/versions/0006_phase32_products.py` (new) — `app.products`, `app.product_images`, CHECK constraints, indexes.
- `rag/database/models.py` — `Product` + `ProductImage` ORM with `selectin` image loading.
- `rag/routers/products.py` (new) — full CRUD, multipart image upload (Pillow→WebP, max 1200px edge), reorder with negative-offset swap, delete with MinIO + Qdrant cleanup. All routes gated by `require_owner`, every query filters by `Product.tenant_id == tenant.id`.
- `rag/products/sync.py` (new) — deterministic `uuid5` point id; `upsert_product_to_qdrant` (embed name+description with retrieval-side bge-small); `delete_product_from_qdrant` (idempotent). Tolerant of Qdrant outages.
- `rag/services/object_store.py` — `ensure_bucket()` helper; `public_url_for()` accepts per-bucket override.
- `rag/retrieval/dense.py` — exposed `embed_text()` passage encoder.
- `rag/config.py` — `minio_bucket_products`, `product_image_max_bytes`, `product_image_max_dim`, `product_max_images`, `product_cta_url_template`.
- `rag/routers/integrations.py` — `POST/GET /api/integrations/messenger/pages` + `DELETE /api/integrations/messenger/pages/{id}`, 409 on cross-tenant rebind.

**Messenger / orchestrator**
- `rag/messenger/payloads.py` — `GenericTemplateButton` / `GenericTemplateElement` / `ProductCarouselBlock`. `ReplyBlock.text` becomes optional (`Field(default=None, min_length=1, max_length=2000)` preserves the Phase 6 empty-string rejection); `ReplyBlock.carousel` added. `build_outbound_payload` accepts dict or instance.
- `rag/messenger/sender.py` — `_format_generic_template()`; `_graph_message_bodies()` ships carousel FIRST then optional text follow-up; pure-text path unchanged for existing flows.
- `rag/messenger/routers/webhook.py` — `messenger.event.attachment_received` structured log per Phase 32.
- `rag/orchestrator/product_branch.py` (new) — messenger-only `enrich_with_products_node`: Qdrant filter `kind=product+tenant_id+is_active=true`, Postgres JOIN with `quantity > 0` filter (source of truth), `_format_carousel` respects all Meta hard limits.
- `rag/orchestrator/state.py` — `product_carousel: dict[str, Any]` state slot.
- `rag/orchestrator/graph.py` — `respond → enrich_with_products → END` (SPA surface short-circuits in the node).
- `rag/main.py` — products router registered under `/api`.

**Frontend**
- `nexus-ui/package.json` — `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`.
- `nexus-ui/src/App.jsx` — `/products` + `/products/:id` under `RequireOwner`.
- `nexus-ui/src/components/layout/Sidebar.jsx` — "Products" link inside `OWNER_NAV`.
- `nexus-ui/src/pages/ProductsDashboardPage.jsx` (new) — search + grid, optimistic delete.
- `nexus-ui/src/pages/ProductEditPage.jsx` (new) — full-page edit, deep-linkable.
- `nexus-ui/src/components/products/ProductsTable.jsx` (new) — card grid with stock badges + CTAs.
- `nexus-ui/src/components/products/ProductForm.jsx` (new) — Etsy-style fields; price in dollars→cents; currency selector.
- `nexus-ui/src/components/products/ImageCarouselEditor.jsx` (new) — `@dnd-kit/sortable` carousel, HTML5 drop-target inside Add tile, optimistic UI, server reconciliation on drop.
- `nexus-ui/src/lib/products.js` (new) — thin API wrapper + `formatPrice` helper.

**Tests + scripts**
- `rag/tests/test_phase32_router_lockdown.py` — static guard on `require_owner` + `tenant_id` filter + page-binding routes.
- `rag/tests/test_phase32_carousel_payloads.py` — Meta hard limits (button ≤20, title/subtitle ≤80, ≤3 buttons, ≤10 elements, ≥1 element), Send API JSON shape, carousel-first ordering, citation stripping.
- `rag/tests/test_phase32_sync_helpers.py` — deterministic `product_point_id`, payload shape, document embedding fallback.
- `rag/tests/test_phase32_product_branch.py` — SPA surface skipped, empty-query/empty-tenant short-circuits, `_truncate`/`_format_price`/`_ctx_url_for` helpers.
- `rag/tests/test_phase32_migration_0006.py` — revision chain + ORM constraint declarations.
- `rag/tests/test_phase32_outbound_payload.py` — dict-vs-instance carousel acceptance + malformed payload rejection.
- `rag/scripts/setup_phase32_products.py` (new) — `ensure_bucket` + Qdrant vector-size probe with actionable error.

## Verification

- `pytest rag/tests/test_phase32_*.py rag/messenger/tests/` → **157 passed**.
- `pytest rag/orchestrator/tests/test_graph_smoke.py rag/orchestrator/tests/test_research_loop.py rag/orchestrator/tests/test_chat_stream_emits_abstain.py` → **20 passed** (graph topology change safe for SPA).
- `ruff check rag/routers/products.py rag/products/sync.py rag/messenger/payloads.py rag/messenger/sender.py rag/orchestrator/product_branch.py rag/database/models.py rag/migrations/versions/0006_phase32_products.py rag/scripts/setup_phase32_products.py rag/routers/integrations.py` → **clean**.
- `npm run build` (nexus-ui) → **exits 0**, 925KB JS / 28KB CSS.

## Architect's strategic decisions honoured

| Question | Decision shipped |
|---|---|
| Qdrant layout | Same `nexus-vault-v2` collection, payload discriminator `kind="product"`. |
| Embedder | Retrieval-side fastembed bge-small (384d) via `embed_text()`. |
| Card CTAs | `web_url` button → `product.url` (per-product) with optional `product_cta_url_template` fallback. |
| Stock-out | Filter at the Postgres JOIN (`quantity > 0 AND is_active`). Carousel hides; preamble text still ships. |

## Deferred to Phase 32.1+

- Postback-driven in-chat checkout (Send Receipt template + cart state).
- Per-tenant CTA URL template (`product_cta_url_template` is global today).
- CDN-stable image URLs (carousel currently mints 1h presigned URLs when no public CDN is configured).
- Visual search routing (attachments are logged + captioned today; product-intent classifier from images is Phase 32.1).
- E2E Playwright spec `phase32_owner_products_crud.spec.ts` — out of scope while ESLint/test infra isn't wired into the FE package.

## Operational notes for deploy

1. Confirm prod env file has `MINIO_BUCKET_PRODUCTS` set (defaults to `nexus-products`).
2. `./deploy-rag.sh` runs `alembic upgrade head` in the api container entrypoint — `0006` applies automatically.
3. Run `uv run python -m rag.scripts.setup_phase32_products` once on the VPS post-deploy to create the bucket + verify Qdrant vector-size invariant.
4. Bind the active page in the SPA: `Settings → Workspaces` (existing) + new `POST /api/integrations/messenger/pages` (or wire the FE panel in a follow-up — backend is ready).
