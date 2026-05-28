"""Phase 32 — Messenger surface product carousel branch.

The branch only fires for ``surface == "messenger"``. SPA queries never
get a carousel — they get the existing text answer with citations.

Pipeline:

    1. Embed ``state["query"]`` with the retrieval-side encoder.
    2. Qdrant search filtered by ``kind == "product"`` and the tenant
       slug; up to ``_TOP_K`` candidates.
    3. Postgres JOIN with ``app.products`` (and ``app.product_images``)
       to filter out ``is_active == False`` and ``quantity <= 0`` and to
       fetch the freshest price + image. Qdrant payload is a best-effort
       cache; the SQL row is the source of truth.
    4. Build a ``ProductCarouselBlock`` (≤ 10 elements, Meta hard limit).
    5. Stamp ``state["product_carousel"]`` with the serialised block;
       ``rag.messenger.payloads.build_outbound_payload`` picks it up and
       attaches it to the ReplyBlock so ``OutboundSender`` ships it as a
       Generic Template message before the text follow-up.

Failure modes (Qdrant down, embedder cold-start, DB hiccup) are tolerated
— the node logs and returns empty; the regular text answer still ships.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from rag.config import settings
from rag.database.engine import get_sessionmaker
from rag.database.models import Product, ProductImage
from rag.messenger.payloads import (
    GenericTemplateButton,
    GenericTemplateElement,
    ProductCarouselBlock,
)
from rag.orchestrator.state import NexusState
from rag.products.sync import product_point_id
from rag.retrieval.dense import embed_text, get_qdrant_client
from rag.services import object_proxy

_log = logging.getLogger(__name__)

_TOP_K = 10  # Meta carousel hard limit
_TITLE_MAX = 80
_SUBTITLE_MAX = 80
_BUTTON_TITLE_MAX = 20


def _truncate(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _format_price(cents: int, currency: str) -> str:
    value = (cents or 0) / 100.0
    return f"{currency} {value:,.2f}"


def _qdrant_filter(tenant_slug: str) -> Filter:
    return Filter(
        must=[
            FieldCondition(key="kind", match=MatchValue(value="product")),
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_slug)),
            FieldCondition(key="is_active", match=MatchValue(value=True)),
        ]
    )


async def _candidate_product_ids(query: str, tenant_slug: str) -> list[uuid.UUID]:
    """Return ranked candidate product UUIDs from Qdrant. Empty on failure."""
    client = get_qdrant_client()
    try:
        vector = await asyncio.get_event_loop().run_in_executor(None, embed_text, query)
    except Exception as exc:  # noqa: BLE001 — embedder cold-start failure
        _log.warning("product_branch.embed_failed: %s", exc)
        return []

    try:
        response = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=_TOP_K,
            with_payload=["product_id"],
            query_filter=_qdrant_filter(tenant_slug),
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("product_branch.qdrant_query_failed: %s", exc)
        return []

    ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for point in response.points:
        payload = dict(point.payload or {})
        raw = payload.get("product_id")
        if not isinstance(raw, str):
            continue
        try:
            pid = uuid.UUID(raw)
        except (TypeError, ValueError):
            continue
        if pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
    return ids


async def _enrich(product_ids: list[uuid.UUID], tenant_slug: str) -> list[Product]:
    """Fetch in-stock active products in Qdrant rank order."""
    if not product_ids:
        return []
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        rows = (
            (
                await db.execute(
                    select(Product).where(
                        Product.id.in_(product_ids),
                        Product.is_active.is_(True),
                        Product.quantity > 0,
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        # Eager-load images per row (the relationship is lazy="selectin" so
        # this fires a single follow-up; safe inside the open session).
        for row in rows:
            _ = list(row.images)

    by_id = {row.id: row for row in rows}
    ordered: list[Product] = []
    for pid in product_ids:
        row = by_id.get(pid)
        if row is not None:
            ordered.append(row)
    return ordered


async def _image_url_for(image: ProductImage) -> str | None:
    """Return a Meta-fetchable absolute URL for ``image``.

    Phase 32.4 — Meta's Send API rejects relative paths and any URL
    embedding an internally-resolvable host (e.g.
    ``http://nexus-minio:9000/...``). Three sources, in order of cost:

    1. ``image.image_url`` — already an absolute CDN URL when
       ``MINIO_PUBLIC_BASE_URL`` is set; cached at upload time.
    2. ``{NEXUS_PUBLIC_BASE_URL}/api/objects/<token>`` — signed bearer
       token proxied through the running app on the public origin.
    3. ``None`` — the carousel formatter drops the element rather than
       ship a URL Meta cannot fetch.
    """
    if image.image_url:
        return image.image_url
    if not image.storage_key:
        return None

    base = (settings.nexus_public_base_url or "").rstrip("/")
    if base:
        try:
            return base + object_proxy.proxy_url(
                bucket=settings.minio_bucket_products,
                key=image.storage_key,
                expires_in=3600,
            )
        except Exception as exc:  # noqa: BLE001 — never raise into webhook
            _log.warning(
                "product_branch.proxy_url_failed key=%s detail=%s",
                image.storage_key,
                exc,
            )
            return None

    _log.warning(
        "product_branch.no_public_image_url key=%s — set NEXUS_PUBLIC_BASE_URL "
        "or MINIO_PUBLIC_BASE_URL so Meta can fetch the carousel image",
        image.storage_key,
    )
    return None


def _ctx_url_for(product: Product) -> str | None:
    if product.url:
        return product.url
    template = (settings.product_cta_url_template or "").strip()
    if not template:
        return None
    try:
        return template.format(slug=product.slug, id=str(product.id))
    except Exception:  # noqa: BLE001
        return None


async def _format_carousel(
    products: list[Product],
) -> ProductCarouselBlock | None:
    elements: list[GenericTemplateElement] = []
    for product in products[:_TOP_K]:
        images = list(product.images or [])
        image_url: str | None = None
        if images:
            image_url = await _image_url_for(images[0])

        subtitle = (
            f"{_format_price(int(product.price_cents), product.currency)} · "
            f"{int(product.quantity)} in stock"
        )

        url = _ctx_url_for(product)
        buttons: list[GenericTemplateButton] = []
        if url:
            buttons.append(
                GenericTemplateButton(
                    type="web_url",
                    title=_truncate("View", _BUTTON_TITLE_MAX),
                    url=url,  # type: ignore[arg-type]
                )
            )

        try:
            elements.append(
                GenericTemplateElement(
                    title=_truncate(product.name, _TITLE_MAX),
                    subtitle=_truncate(subtitle, _SUBTITLE_MAX),
                    image_url=image_url,  # type: ignore[arg-type]
                    buttons=buttons,
                )
            )
        except Exception as exc:  # noqa: BLE001 — defensive: never raise into webhook
            _log.warning(
                "product_branch.element_skipped product_id=%s detail=%s",
                product.id,
                exc,
            )
            continue

    if not elements:
        return None
    return ProductCarouselBlock(elements=elements)


async def enrich_with_products_node(state: NexusState) -> dict[str, Any]:
    """LangGraph node — attach a product carousel for messenger surface."""
    surface = state.get("surface")
    if surface != "messenger":
        return {}
    query = (state.get("query") or "").strip()
    tenant_slug = state.get("tenant_id")
    if not query or not tenant_slug:
        return {}

    candidate_ids = await _candidate_product_ids(query, tenant_slug)
    if not candidate_ids:
        _log.info(
            "product_branch.no_candidates tenant=%s query_len=%d",
            tenant_slug,
            len(query),
        )
        return {}

    products = await _enrich(candidate_ids, tenant_slug)
    if not products:
        _log.info(
            "product_branch.no_in_stock_matches tenant=%s candidates=%d",
            tenant_slug,
            len(candidate_ids),
        )
        return {}

    carousel = await _format_carousel(products)
    if carousel is None:
        return {}

    _log.info(
        "product_branch.carousel_built tenant=%s elements=%d",
        tenant_slug,
        len(carousel.elements),
    )
    return {"product_carousel": carousel.model_dump(mode="json")}


__all__ = [
    "enrich_with_products_node",
    "product_point_id",
]
