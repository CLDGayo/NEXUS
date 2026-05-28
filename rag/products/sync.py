"""Phase 32 — Hybrid sync: Postgres product rows ↔ Qdrant semantic index.

A product is stored in three places:

    * ``app.products`` — authoritative inventory + pricing (this row is
      the source of truth for ``quantity > 0`` checks).
    * MinIO ``{minio_bucket_products}/{tenant_slug}/{product_id}/...`` —
      normalised WebP image blobs, listed by ``app.product_images``.
    * Qdrant ``settings.qdrant_collection`` — one point per product, keyed
      by ``uuid5(NAMESPACE_PRODUCTS, str(product.id))`` so reupserting a
      product is idempotent and never collides with a different product.

The Qdrant payload carries every field the customer-facing carousel
needs to filter on before falling back to a Postgres JOIN: ``kind``,
``tenant_id`` (slug — matches the existing payload convention used by the
document arm), ``product_id``, ``is_active``, ``quantity``, ``price_cents``,
``currency``, ``name``, ``url``.

``upsert_product_to_qdrant`` is the single write path; ``delete_product_from_qdrant``
is the single delete path. Both are tolerant of Qdrant being unreachable
(log + continue) — the Postgres row remains authoritative and a later
reconcile sweep can rebuild the index.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from rag.config import settings
from rag.database.models import Product
from rag.retrieval.dense import embed_text, get_qdrant_client

_log = logging.getLogger(__name__)

# Stable namespace for deterministic Qdrant point ids. Hard-coded — never
# regenerate; rotating this would orphan every existing product vector.
NAMESPACE_PRODUCTS = uuid.UUID("c9b1e5e2-1c5a-4f4f-9a2b-d3f0c0a9b1b2")


def product_point_id(product_id: uuid.UUID) -> str:
    """Deterministic Qdrant point id for a product row.

    Stable across re-creates: deleting a product and re-creating it with
    the same UUID returns the same point id. Different products never
    collide.
    """
    return str(uuid.uuid5(NAMESPACE_PRODUCTS, str(product_id)))


def _payload(product: Product, tenant_slug: str) -> dict[str, Any]:
    description = (product.description or "").strip()
    body_text = f"{product.name}\n\n{description}" if description else product.name
    return {
        "kind": "product",
        "product_id": str(product.id),
        "tenant_id": tenant_slug,
        # Document-compatible keys so ``_qdrant_index_summary`` and the
        # citation renderer treat products as first-class documents. The
        # ``file`` path mirrors ``_product_to_doc_dict`` in the documents
        # router, which the SPA already keys ``indexSummary`` on.
        "file": f"/products/{product.slug}",
        "title": product.name,
        "text": body_text,
        "heading_path": [product.name],
        "folder": "/products",
        "source_kind": "product",
        # Carousel filter fields (Phase 32 contract).
        "name": product.name,
        "price_cents": int(product.price_cents),
        "currency": product.currency,
        "is_active": bool(product.is_active),
        "quantity": int(product.quantity),
        "url": product.url,
    }


def _embed_document(product: Product) -> list[float]:
    """Embed ``{name}\\n\\n{description}`` as a passage.

    Falls back to embedding the name alone if the description is empty so
    a brand-new product still gets a usable vector before its description
    is filled in.
    """
    body = product.description.strip()
    text = f"{product.name}\n\n{body}" if body else product.name
    return embed_text(text)


async def upsert_product_to_qdrant(
    product: Product, *, tenant_slug: str, client: AsyncQdrantClient | None = None
) -> None:
    """Embed + upsert the product into the live Qdrant collection.

    Skips (no-op) and triggers a delete when the product is inactive or
    out of stock — the carousel formatter filters on these post-JOIN, but
    keeping the index clean reduces wasted top-K slots and avoids leaking
    stale prices through the payload cache.

    Tolerant of Qdrant failures: logs a warning, returns. The Postgres
    row remains the source of truth and a reconcile pass can rebuild the
    point later.
    """
    qdrant = client if client is not None else get_qdrant_client()

    if not product.is_active or product.quantity <= 0:
        await delete_product_from_qdrant(product.id, client=qdrant)
        return

    try:
        vector = await asyncio.get_event_loop().run_in_executor(
            None, _embed_document, product
        )
    except Exception as exc:  # noqa: BLE001 — embedder cold-start failure
        _log.warning(
            "products.sync.embed_failed product_id=%s tenant=%s detail=%s",
            product.id,
            tenant_slug,
            exc,
        )
        return

    point = PointStruct(
        id=product_point_id(product.id),
        vector=vector,
        payload=_payload(product, tenant_slug),
    )
    try:
        await qdrant.upsert(
            collection_name=settings.qdrant_collection,
            points=[point],
        )
    except Exception as exc:  # noqa: BLE001 — Postgres row is the truth
        _log.warning(
            "products.sync.upsert_failed product_id=%s tenant=%s detail=%s",
            product.id,
            tenant_slug,
            exc,
        )
        return

    _log.info(
        "products.sync.upserted product_id=%s tenant=%s collection=%s",
        product.id,
        tenant_slug,
        settings.qdrant_collection,
    )


async def delete_product_from_qdrant(
    product_id: uuid.UUID, *, client: AsyncQdrantClient | None = None
) -> None:
    """Delete the product point by deterministic id. Idempotent."""
    qdrant = client if client is not None else get_qdrant_client()
    try:
        await qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=[product_point_id(product_id)],
        )
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        _log.warning(
            "products.sync.delete_failed product_id=%s detail=%s",
            product_id,
            exc,
        )
        return
    _log.info(
        "products.sync.deleted product_id=%s collection=%s",
        product_id,
        settings.qdrant_collection,
    )
