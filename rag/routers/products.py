"""Phase 32 — Product catalog CRUD + image registry router.

Every route is owner-gated by ``require_owner`` (Phase 31): the JWT must
identify a tenant member whose role is ``owner``. The active tenant id
is the row-level filter for every select/insert/update/delete, so an
owner of workspace A cannot see, mutate, or delete a product in
workspace B even by guessing UUIDs (cross-tenant attempts return 404).

Hybrid sync:
    * Product create / update -> ``upsert_product_to_qdrant`` (best-effort).
    * Product delete           -> ``delete_product_from_qdrant`` (best-effort).
    * is_active=False / quantity=0 -> Qdrant point removed (carousel hides).

Image pipeline:
    * Multipart upload accepts jpg/png/webp, ≤ ``settings.product_image_max_bytes``.
    * Pillow normalises to WebP, max edge ``settings.product_image_max_dim``.
    * Stored at ``{minio_bucket_products}/{tenant_slug}/{product_id}/{image_id}.webp``.
    * Reorder runs inside a transaction with a negative-offset swap so the
      ``UNIQUE (product_id, display_order)`` constraint is never violated
      mid-statement under concurrent edits.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import Product, ProductImage, Tenant
from rag.products.sync import (
    delete_product_from_qdrant,
    upsert_product_to_qdrant,
)
from rag.services import object_store
from routers.deps import require_owner

_log = logging.getLogger(__name__)

router = APIRouter(tags=["products"])

_ALLOWED_MIME = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)
_OUTPUT_CONTENT_TYPE = "image/webp"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ─── Pydantic schemas ───────────────────────────────────────────────────────


class ProductImageRead(BaseModel):
    id: uuid.UUID
    storage_key: str
    image_url: str | None
    display_order: int
    width: int | None
    height: int | None
    content_type: str


class ProductRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    description: str
    price_cents: int
    currency: str
    quantity: int
    is_active: bool
    url: str | None
    extra_metadata: dict[str, Any]
    images: list[ProductImageRead]


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    price_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    quantity: int = Field(default=0, ge=0)
    is_active: bool = True
    url: HttpUrl | None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    quantity: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    url: HttpUrl | None = None
    extra_metadata: dict[str, Any] | None = None


class ImageOrderRequest(BaseModel):
    ordered_ids: list[uuid.UUID] = Field(..., min_length=1)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Lowercase, dash-separated, alpha-num only. Trims to 120 chars."""
    base = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return (base or "product")[:120]


async def _next_unique_slug(
    db: AsyncSession, tenant_id: uuid.UUID, base: str
) -> str:
    """Return a slug unique to the tenant. Appends a short uuid on collision."""
    candidate = base
    existing = (
        await db.execute(
            select(Product.id).where(
                Product.tenant_id == tenant_id, Product.slug == candidate
            )
        )
    ).first()
    if existing is None:
        return candidate
    suffix = uuid.uuid4().hex[:6]
    return f"{base[:120 - 7]}-{suffix}"


def _resolve_image_url(storage_key: str) -> str | None:
    """CDN URL when configured, otherwise let the carousel format mint a presigned."""
    return object_store.public_url_for(
        storage_key, bucket=settings.minio_bucket_products
    )


def _serialize_image(img: ProductImage) -> ProductImageRead:
    return ProductImageRead.model_validate(img, from_attributes=True)


def _serialize_product(product: Product) -> ProductRead:
    return ProductRead(
        id=product.id,
        tenant_id=product.tenant_id,
        name=product.name,
        slug=product.slug,
        description=product.description,
        price_cents=int(product.price_cents),
        currency=product.currency,
        quantity=int(product.quantity),
        is_active=bool(product.is_active),
        url=product.url,
        extra_metadata=dict(product.extra_metadata or {}),
        images=[_serialize_image(im) for im in (product.images or [])],
    )


async def _get_product_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> Product:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == product_id, Product.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="product_not_found")
    return product


def _normalise_to_webp(raw: bytes, *, max_dim: int) -> tuple[bytes, int, int]:
    """Decode + downscale (preserving aspect) + re-encode as WebP.

    Returns ``(bytes, width, height)`` of the final image. Raises
    HTTPException(415) when Pillow cannot decode the input.
    """
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            width, height = img.width, img.height
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=85, method=6)
            return out.getvalue(), width, height
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=415, detail="UNSUPPORTED_IMAGE_FORMAT"
        ) from exc


def _image_storage_key(
    tenant_slug: str, product_id: uuid.UUID, image_id: uuid.UUID
) -> str:
    return f"{tenant_slug}/{product_id}/{image_id}.webp"


# ─── Product CRUD ───────────────────────────────────────────────────────────


@router.get("/products")
async def list_products(
    search: str = Query("", max_length=200),
    active_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """List products for the active tenant."""
    base = select(Product).where(Product.tenant_id == tenant.id)
    if active_only:
        base = base.where(Product.is_active.is_(True))
    if search:
        needle = f"%{search}%"
        base = base.where(
            or_(
                Product.name.ilike(needle),
                Product.description.ilike(needle),
            )
        )

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    stmt = (
        base.order_by(Product.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    products = (await db.execute(stmt)).scalars().unique().all()
    return {
        "items": [_serialize_product(p).model_dump(mode="json") for p in products],
        "total": int(total),
        "page": page,
        "limit": limit,
    }


@router.post("/products", status_code=201)
async def create_product(
    body: ProductCreate,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    base_slug = _slugify(body.name)
    slug = await _next_unique_slug(db, tenant.id, base_slug)
    product = Product(
        tenant_id=tenant.id,
        name=body.name,
        slug=slug,
        description=body.description,
        price_cents=body.price_cents,
        currency=body.currency.upper(),
        quantity=body.quantity,
        is_active=body.is_active,
        url=str(body.url) if body.url is not None else None,
        extra_metadata=dict(body.extra_metadata),
    )
    db.add(product)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="product_slug_conflict"
        ) from exc
    await db.refresh(product, attribute_names=["images"])

    await upsert_product_to_qdrant(product, tenant_slug=tenant.slug)
    return _serialize_product(product).model_dump(mode="json")


@router.get("/products/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    product = await _get_product_or_404(db, tenant.id, product_id)
    return _serialize_product(product).model_dump(mode="json")


@router.patch("/products/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    product = await _get_product_or_404(db, tenant.id, product_id)

    changes = body.model_dump(exclude_unset=True)
    semantic_dirty = "name" in changes or "description" in changes

    if "name" in changes and changes["name"]:
        product.name = changes["name"]
    if "description" in changes and changes["description"] is not None:
        product.description = changes["description"]
    if "price_cents" in changes and changes["price_cents"] is not None:
        product.price_cents = int(changes["price_cents"])
    if "currency" in changes and changes["currency"]:
        product.currency = str(changes["currency"]).upper()
    if "quantity" in changes and changes["quantity"] is not None:
        product.quantity = int(changes["quantity"])
    if "is_active" in changes and changes["is_active"] is not None:
        product.is_active = bool(changes["is_active"])
    if "url" in changes:
        product.url = (
            str(changes["url"]) if changes["url"] is not None else None
        )
    if "extra_metadata" in changes and changes["extra_metadata"] is not None:
        product.extra_metadata = dict(changes["extra_metadata"])

    await db.commit()
    await db.refresh(product, attribute_names=["images"])

    # Re-embed if the semantic surface changed, otherwise just refresh the
    # payload so price/quantity/url update in Qdrant for the carousel cache.
    if semantic_dirty or not product.is_active or product.quantity <= 0:
        await upsert_product_to_qdrant(product, tenant_slug=tenant.slug)
    else:
        await upsert_product_to_qdrant(product, tenant_slug=tenant.slug)

    return _serialize_product(product).model_dump(mode="json")


@router.delete(
    "/products/{product_id}", status_code=204, response_class=Response
)
async def delete_product(
    product_id: uuid.UUID,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    product = await _get_product_or_404(db, tenant.id, product_id)

    # MinIO cleanup first — the DB cascade deletes the image rows after.
    for img in list(product.images or []):
        try:
            await object_store.delete_object(
                bucket=settings.minio_bucket_products, key=img.storage_key
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "products.delete.minio_failed key=%s detail=%s",
                img.storage_key,
                exc,
            )

    await db.delete(product)
    await db.commit()

    await delete_product_from_qdrant(product_id)
    return Response(status_code=204)


# ─── Product image management ───────────────────────────────────────────────


@router.post("/products/{product_id}/images", status_code=201)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(..., description="JPG / PNG / WEBP image."),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    product = await _get_product_or_404(db, tenant.id, product_id)

    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"UNSUPPORTED_MIME ({file.content_type or 'unknown'})",
        )

    if len(product.images or []) >= settings.product_max_images:
        raise HTTPException(
            status_code=409,
            detail=f"MAX_IMAGES_REACHED ({settings.product_max_images})",
        )

    limit = settings.product_image_max_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=413, detail=f"IMAGE_TOO_LARGE (limit {limit} bytes)"
        )
    if not raw:
        raise HTTPException(status_code=400, detail="EMPTY_BODY")

    encoded, width, height = _normalise_to_webp(
        raw, max_dim=settings.product_image_max_dim
    )

    image_id = uuid.uuid4()
    key = _image_storage_key(tenant.slug, product.id, image_id)

    await object_store.put_object(
        bucket=settings.minio_bucket_products,
        key=key,
        body=encoded,
        content_type=_OUTPUT_CONTENT_TYPE,
    )

    next_order = (
        await db.execute(
            select(func.coalesce(func.max(ProductImage.display_order), -1)).where(
                ProductImage.product_id == product.id
            )
        )
    ).scalar_one()

    image = ProductImage(
        id=image_id,
        product_id=product.id,
        storage_key=key,
        image_url=_resolve_image_url(key),
        display_order=int(next_order) + 1,
        width=width,
        height=height,
        content_type=_OUTPUT_CONTENT_TYPE,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    return _serialize_image(image).model_dump(mode="json")


@router.patch("/products/{product_id}/images/order")
async def reorder_product_images(
    product_id: uuid.UUID,
    body: ImageOrderRequest,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    product = await _get_product_or_404(db, tenant.id, product_id)
    images = list(product.images or [])
    by_id = {im.id: im for im in images}

    if set(body.ordered_ids) != set(by_id.keys()):
        raise HTTPException(
            status_code=400, detail="ORDERED_IDS_MISMATCH"
        )

    # Two-pass swap: first push every row into the negative range so the
    # UNIQUE (product_id, display_order) constraint cannot fire mid-update,
    # then write the final 0..N-1 positions.
    for img in images:
        img.display_order = -1000 - int(img.display_order)
    await db.flush()

    for idx, image_id in enumerate(body.ordered_ids):
        by_id[image_id].display_order = idx
    await db.commit()

    refreshed = (
        await db.execute(
            select(ProductImage)
            .where(ProductImage.product_id == product.id)
            .order_by(ProductImage.display_order)
        )
    ).scalars().all()
    return {"images": [_serialize_image(im).model_dump(mode="json") for im in refreshed]}


@router.delete(
    "/products/{product_id}/images/{image_id}",
    status_code=204,
    response_class=Response,
)
async def delete_product_image(
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    product = await _get_product_or_404(db, tenant.id, product_id)
    images = list(product.images or [])
    target = next((im for im in images if im.id == image_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="image_not_found")

    try:
        await object_store.delete_object(
            bucket=settings.minio_bucket_products, key=target.storage_key
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "products.image.delete.minio_failed key=%s detail=%s",
            target.storage_key,
            exc,
        )

    await db.delete(target)
    await db.flush()

    # Recompact display_order for remaining images so the next upload
    # appends at a known index (negative-offset swap, same as reorder).
    remaining = [im for im in images if im.id != image_id]
    remaining.sort(key=lambda im: int(im.display_order))
    for im in remaining:
        im.display_order = -1000 - int(im.display_order)
    await db.flush()
    for idx, im in enumerate(remaining):
        im.display_order = idx
    await db.commit()
    return Response(status_code=204)
