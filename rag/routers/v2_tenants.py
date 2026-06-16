"""Phase 29 — tenant CRUD endpoints.

* ``POST /api/tenants``  — create a tenant. Caller becomes ``owner``.
* ``GET  /api/tenants``  — list tenants the caller belongs to (with role).
* ``GET  /api/tenants/{id}`` — single-tenant detail, gated by membership.

Phase 50 — workspace member management (manager-gated):

* ``GET    /api/tenants/{id}/members``           — list members with roles.
* ``PATCH  /api/tenants/{id}/members/{user_id}`` — change a member's role.
* ``DELETE /api/tenants/{id}/members/{user_id}`` — remove a member.

Phase 52 — Workspace Lifecycle & Danger Zone (manager- or owner-gated):

* ``PATCH  /api/tenants/{id}``          — rename/reslug/avatar_url (manager).
* ``POST   /api/tenants/{id}/avatar``   — upload WebP avatar (manager).
* ``DELETE /api/tenants/{id}/avatar``   — remove avatar (manager).
* ``POST   /api/tenants/{id}/archive``  — soft-delete (owner).
* ``POST   /api/tenants/{id}/unarchive``— restore (owner).
* ``POST   /api/tenants/{id}/transfer`` — transfer ownership (owner).
* ``DELETE /api/tenants/{id}``          — hard-delete + Qdrant purge (owner).

Slug uniqueness collisions surface as 409. Empty / whitespace-only names
are rejected at the schema layer (``min_length=1``).
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import (
    MemberRead,
    MemberRoleUpdate,
    TenantCreate,
    TenantRead,
    TenantUpdate,
    current_active_user,
    list_tenants_for_user,
    slugify_tenant_name,
)
from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import Document, Message, Product, Tenant, TenantUser, User
from rag.retrieval.dense import get_qdrant_client
from rag.services import object_store
from routers.deps import require_manager, require_owner

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


@router.post("", response_model=TenantRead, status_code=201)
async def create_tenant(
    body: TenantCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Create a new tenant and bind the requesting user as ``owner``."""

    slug = slugify_tenant_name(body.slug or body.name)

    tenant = Tenant(name=body.name.strip(), slug=slug)
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"tenant slug already exists: {slug!r}"
        ) from exc

    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner"))
    await db.commit()
    await db.refresh(tenant)

    _log.info(
        "tenant.create user_id=%s tenant_id=%s slug=%s",
        str(user.id),
        str(tenant.id),
        slug,
    )
    return TenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        created_at=tenant.created_at,
        role="owner",
        avatar_url=tenant.avatar_url,
        archived_at=tenant.archived_at,
    )


@router.get("", response_model=list[TenantRead])
async def list_my_tenants(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> list[TenantRead]:
    return await list_tenants_for_user(db, user)


@router.get("/{tenant_id}", response_model=TenantRead)
async def get_tenant_detail(
    tenant_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Return a single tenant. Phase 50 gated by ``require_manager`` —
    owners and admins of the active workspace can read its detail payload
    (admins need it for the Workspace Manager detail page). The path id
    must match the ``X-Tenant-ID`` header so a curl that swaps either one
    is rejected before a row is read."""

    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )

    # require_manager already verified the role; re-read for the response
    # payload (the link row is cached in the same session, so this is
    # not an extra round-trip in practice).
    link = await db.get(TenantUser, (tenant.id, user.id))
    role = link.role if link else "owner"

    return TenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        created_at=tenant.created_at,
        role=role,
        avatar_url=tenant.avatar_url,
        archived_at=tenant.archived_at,
    )


# ---------------------------------------------------------------------------
# Phase 50 — member management
# ---------------------------------------------------------------------------


def _check_path_matches_header(tenant: Tenant, tenant_id: uuid.UUID) -> None:
    """Reject requests whose path id disagrees with ``X-Tenant-ID``."""

    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )


async def _count_owners(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(TenantUser)
        .where(TenantUser.tenant_id == tenant_id, TenantUser.role == "owner")
    )
    return (await db.execute(stmt)).scalar_one()


@router.get("/{tenant_id}/members", response_model=list[MemberRead])
async def list_members(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[MemberRead]:
    """List every member of the workspace with their role.

    Owners sort first, then admins, then members; ties break on join
    date so the list is stable across refreshes.
    """

    _check_path_matches_header(tenant, tenant_id)

    stmt = (
        select(User, TenantUser.role, TenantUser.created_at)
        .join(TenantUser, TenantUser.user_id == User.id)
        .where(TenantUser.tenant_id == tenant.id)
        .order_by(TenantUser.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    rank = {"owner": 0, "admin": 1, "member": 2}
    rows.sort(key=lambda r: rank.get(r[1], 3))
    return [
        MemberRead(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=role,
            joined_at=joined_at,
        )
        for user, role, joined_at in rows
    ]


@router.patch("/{tenant_id}/members/{member_user_id}", response_model=MemberRead)
async def update_member_role(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    body: MemberRoleUpdate,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> MemberRead:
    """Change a member's role with Phase 50 RBAC guards:

    * Admins cannot touch owners (escalation fence) nor grant ``owner``.
    * The last owner can never be demoted — transfer ownership first.
    """

    _check_path_matches_header(tenant, tenant_id)

    caller_link = await db.get(TenantUser, (tenant.id, user.id))
    target_link = await db.get(TenantUser, (tenant.id, member_user_id))
    if target_link is None:
        raise HTTPException(status_code=404, detail="member not found")

    caller_role = caller_link.role if caller_link else "member"

    if caller_role != "owner":
        if target_link.role == "owner":
            raise HTTPException(status_code=403, detail="admins cannot modify owners")
        if body.role == "owner":
            raise HTTPException(
                status_code=403, detail="only owners can grant the owner role"
            )

    if target_link.role == "owner" and body.role != "owner":
        if await _count_owners(db, tenant.id) <= 1:
            raise HTTPException(
                status_code=409,
                detail="cannot demote the last owner — transfer ownership first",
            )

    target_link.role = body.role
    await db.commit()

    target_user = await db.get(User, member_user_id)
    if target_user is None:  # FK guarantees this; guard for type-safety.
        raise HTTPException(status_code=404, detail="member not found")

    _log.info(
        "tenant.member.role_change tenant_id=%s actor=%s target=%s role=%s",
        str(tenant.id),
        str(user.id),
        str(member_user_id),
        body.role,
    )
    return MemberRead(
        user_id=target_user.id,
        email=target_user.email,
        display_name=target_user.display_name,
        role=target_link.role,
        joined_at=target_link.created_at,
    )


@router.delete(
    "/{tenant_id}/members/{member_user_id}",
    status_code=204,
    response_class=Response,
)
async def remove_member(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    """Remove a member from the workspace.

    Guards: admins cannot remove owners; the last owner can never be
    removed (including self-removal) — transfer ownership first.
    """

    _check_path_matches_header(tenant, tenant_id)

    caller_link = await db.get(TenantUser, (tenant.id, user.id))
    target_link = await db.get(TenantUser, (tenant.id, member_user_id))
    if target_link is None:
        raise HTTPException(status_code=404, detail="member not found")

    caller_role = caller_link.role if caller_link else "member"

    if caller_role != "owner" and target_link.role == "owner":
        raise HTTPException(status_code=403, detail="admins cannot remove owners")

    if target_link.role == "owner":
        if await _count_owners(db, tenant.id) <= 1:
            raise HTTPException(
                status_code=409,
                detail="cannot remove the last owner — transfer ownership first",
            )

    await db.delete(target_link)
    await db.commit()

    _log.info(
        "tenant.member.remove tenant_id=%s actor=%s target=%s",
        str(tenant.id),
        str(user.id),
        str(member_user_id),
    )

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Phase 52 — Workspace Lifecycle & Danger Zone
# ---------------------------------------------------------------------------

_ALLOWED_AVATAR_MIME = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp"})
_AVATAR_CONTENT_TYPE = "image/webp"


def _tenant_avatar_key(tenant: Tenant) -> str:
    return f"tenant/{tenant.id}.webp"


def _normalise_tenant_avatar(raw: bytes, *, size: int) -> bytes:
    """Decode + downscale to ``size×size`` WebP. Raises 415 for non-images."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (size, size), (255, 255, 255))
            paste_x = (size - img.width) // 2
            paste_y = (size - img.height) // 2
            canvas.paste(img, (paste_x, paste_y))
            out = io.BytesIO()
            canvas.save(out, format="WEBP", quality=85, method=6)
            return out.getvalue()
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=415, detail="UNSUPPORTED_IMAGE_FORMAT"
        ) from exc


def _tenant_read_from_model(tenant: Tenant, role: str) -> TenantRead:
    """Build a TenantRead from a Tenant ORM row (no member_count)."""
    return TenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        created_at=tenant.created_at,
        role=role,
        avatar_url=tenant.avatar_url,
        archived_at=tenant.archived_at,
    )


class _TransferOwnershipBody(BaseModel):
    new_owner_user_id: uuid.UUID


class _DeleteWorkspaceBody(BaseModel):
    confirm_name: str


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Rename, reslug, or update avatar_url for the workspace.

    Slug changes are blocked when the tenant has indexed documents (Qdrant
    payload keys are keyed by slug; a rename would orphan all vectors).
    Slug uniqueness is enforced at the DB level (409 ``slug_taken``).
    """
    _check_path_matches_header(tenant, tenant_id)

    # Read caller role for the response
    caller_link = await db.get(TenantUser, (tenant.id, user.id))
    role = caller_link.role if caller_link else "owner"

    changed = False
    slug_changed = False
    new_slug: str | None = None

    if body.name is not None:
        stripped = body.name.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail="name cannot be blank")
        tenant.name = stripped
        changed = True

    if body.slug is not None and body.slug != tenant.slug:
        # Block slug change when documents exist — Qdrant payload keys are
        # tenant slug-based; renaming now would create orphan vectors.
        doc_count_stmt = (
            select(func.count())
            .select_from(Document)
            .where(Document.tenant_id == tenant.id)
        )
        doc_count: int = (await db.execute(doc_count_stmt)).scalar_one()
        if doc_count > 0:
            raise HTTPException(
                status_code=409,
                detail="slug_change_blocked_documents_exist",
            )
        new_slug = body.slug
        tenant.slug = new_slug
        slug_changed = True
        changed = True

    if body.avatar_url is not None:
        tenant.avatar_url = body.avatar_url
        changed = True

    if not changed:
        return _tenant_read_from_model(tenant, role)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="slug_taken")
    await db.refresh(tenant)

    _log.info(
        "tenant.update tenant_id=%s actor=%s slug_changed=%s",
        str(tenant.id),
        str(user.id),
        slug_changed,
    )

    result = _tenant_read_from_model(tenant, role)
    if slug_changed:
        # Surface a warning in the response body comment — we return the
        # payload and let the client handle any integration-link messaging.
        _log.warning(
            "tenant.slug_changed tenant_id=%s old_slug=%s new_slug=%s",
            str(tenant.id),
            body.slug,
            new_slug,
        )
    return result


@router.post("/{tenant_id}/avatar", response_model=TenantRead)
async def upload_tenant_avatar(
    tenant_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="JPG / PNG / WEBP, ≤2 MB.")],
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Upload and normalise a workspace avatar image."""
    _check_path_matches_header(tenant, tenant_id)

    caller_link = await db.get(TenantUser, (tenant.id, user.id))
    role = caller_link.role if caller_link else "owner"

    if file.content_type not in _ALLOWED_AVATAR_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"UNSUPPORTED_MIME ({file.content_type or 'unknown'})",
        )

    limit = settings.avatar_max_upload_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"AVATAR_TOO_LARGE (limit {limit} bytes)",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="EMPTY_BODY")

    normalised = _normalise_tenant_avatar(raw, size=settings.avatar_output_size)

    key = _tenant_avatar_key(tenant)
    await object_store.put_object(
        bucket=settings.minio_bucket_avatars,
        key=key,
        body=normalised,
        content_type=_AVATAR_CONTENT_TYPE,
    )

    public_url = object_store.public_url_for(key)
    tenant.avatar_url = public_url or f"minio:{key}"
    await db.commit()
    await db.refresh(tenant)

    _log.info(
        "tenant.avatar.uploaded tenant_id=%s key=%s bytes=%d",
        str(tenant.id),
        key,
        len(normalised),
    )
    return _tenant_read_from_model(tenant, role)


@router.delete("/{tenant_id}/avatar", response_model=TenantRead)
async def delete_tenant_avatar(
    tenant_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Remove the workspace avatar from object storage and null the column."""
    _check_path_matches_header(tenant, tenant_id)

    caller_link = await db.get(TenantUser, (tenant.id, user.id))
    role = caller_link.role if caller_link else "owner"

    key = _tenant_avatar_key(tenant)
    try:
        await object_store.delete_object(
            bucket=settings.minio_bucket_avatars, key=key
        )
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup
        _log.warning(
            "tenant.avatar.delete_blob_failed tenant_id=%s key=%s detail=%s",
            str(tenant.id),
            key,
            exc,
        )

    tenant.avatar_url = None
    await db.commit()
    await db.refresh(tenant)

    _log.info("tenant.avatar.deleted tenant_id=%s", str(tenant.id))
    return _tenant_read_from_model(tenant, role)


@router.post("/{tenant_id}/archive", response_model=TenantRead)
async def archive_tenant(
    tenant_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Soft-delete the workspace. Data routes return 403 ``workspace_archived``
    while archived. Only the owner can archive."""
    _check_path_matches_header(tenant, tenant_id)

    if tenant.archived_at is not None:
        raise HTTPException(status_code=409, detail="already_archived")

    tenant.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tenant)

    _log.info("tenant.archived tenant_id=%s actor=%s", str(tenant.id), str(user.id))
    return _tenant_read_from_model(tenant, "owner")


@router.post("/{tenant_id}/unarchive", response_model=TenantRead)
async def unarchive_tenant(
    tenant_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Restore an archived workspace."""
    _check_path_matches_header(tenant, tenant_id)

    if tenant.archived_at is None:
        raise HTTPException(status_code=409, detail="not_archived")

    tenant.archived_at = None
    await db.commit()
    await db.refresh(tenant)

    _log.info(
        "tenant.unarchived tenant_id=%s actor=%s", str(tenant.id), str(user.id)
    )
    return _tenant_read_from_model(tenant, "owner")


@router.post("/{tenant_id}/transfer", response_model=TenantRead)
async def transfer_ownership(
    tenant_id: uuid.UUID,
    body: _TransferOwnershipBody,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Transfer workspace ownership to another member.

    Guards:
    * Target must be a member (404 ``member_not_found``).
    * Target must not already be an owner (409).
    * Caller cannot transfer to themselves (409).
    After transfer: target → ``owner``, caller → ``admin``.
    """
    _check_path_matches_header(tenant, tenant_id)

    if body.new_owner_user_id == user.id:
        raise HTTPException(
            status_code=409, detail="cannot transfer ownership to yourself"
        )

    target_link = await db.get(TenantUser, (tenant.id, body.new_owner_user_id))
    if target_link is None:
        raise HTTPException(status_code=404, detail="member_not_found")

    if target_link.role == "owner":
        raise HTTPException(
            status_code=409, detail="target is already an owner"
        )

    caller_link = await db.get(TenantUser, (tenant.id, user.id))

    # Atomic: promote target, demote caller — one commit.
    target_link.role = "owner"
    if caller_link is not None:
        caller_link.role = "admin"
    await db.commit()
    await db.refresh(tenant)

    _log.info(
        "tenant.ownership_transferred tenant_id=%s from=%s to=%s",
        str(tenant.id),
        str(user.id),
        str(body.new_owner_user_id),
    )
    # Return caller's new role (admin after transfer)
    new_caller_role = caller_link.role if caller_link else "admin"
    return _tenant_read_from_model(tenant, new_caller_role)


# ---------------------------------------------------------------------------
# Phase 53 — WM-4 Usage Dashboard
# ---------------------------------------------------------------------------


class _DayCount(BaseModel):
    date: str  # ISO date string "YYYY-MM-DD"
    count: int


class TenantUsageRead(BaseModel):
    document_count: int
    product_count: int
    member_count: int
    vector_chunks: int | None
    messages_7d: list[_DayCount]
    messages_total: int


@router.get("/{tenant_id}/usage", response_model=TenantUsageRead)
async def get_tenant_usage(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> TenantUsageRead:
    """Return usage stats for the workspace.

    Gated by ``require_manager`` (owner|admin). Path id must match the
    ``X-Tenant-ID`` header — ``_check_path_matches_header`` enforces this.

    Vector chunk count is a live Qdrant ``count`` by slug filter. On any
    Qdrant error the field degrades to ``null`` rather than 500.
    """
    _check_path_matches_header(tenant, tenant_id)

    # --- Postgres counts ---------------------------------------------------

    doc_stmt = (
        select(func.count())
        .select_from(Document)
        .where(Document.tenant_id == tenant.id)
    )
    document_count: int = (await db.execute(doc_stmt)).scalar_one()

    product_stmt = (
        select(func.count())
        .select_from(Product)
        .where(Product.tenant_id == tenant.id)
    )
    product_count: int = (await db.execute(product_stmt)).scalar_one()

    member_stmt = (
        select(func.count())
        .select_from(TenantUser)
        .where(TenantUser.tenant_id == tenant.id)
    )
    member_count: int = (await db.execute(member_stmt)).scalar_one()

    msg_total_stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.tenant_id == tenant.id)
    )
    messages_total: int = (await db.execute(msg_total_stmt)).scalar_one()

    # --- 7-day message volume (UTC date buckets, zero-filled) ---------------
    today_utc = datetime.now(timezone.utc).date()
    seven_days_ago = today_utc - timedelta(days=6)

    msg_7d_stmt = (
        select(
            cast(Message.created_at, DATE).label("day"),
            func.count().label("cnt"),
        )
        .where(
            Message.tenant_id == tenant.id,
            Message.created_at >= datetime(
                seven_days_ago.year,
                seven_days_ago.month,
                seven_days_ago.day,
                tzinfo=timezone.utc,
            ),
        )
        .group_by(cast(Message.created_at, DATE))
        .order_by(cast(Message.created_at, DATE))
    )
    rows_7d = (await db.execute(msg_7d_stmt)).all()

    # Build a zero-filled series for all 7 days
    day_counts: dict[date, int] = {
        today_utc - timedelta(days=i): 0 for i in range(6, -1, -1)
    }
    for row in rows_7d:
        d: date = row.day if isinstance(row.day, date) else date.fromisoformat(str(row.day))
        if d in day_counts:
            day_counts[d] = row.cnt
    messages_7d = [
        _DayCount(date=d.isoformat(), count=c)
        for d, c in sorted(day_counts.items())
    ]

    # --- Qdrant vector chunk count (graceful degrade) -----------------------
    vector_chunks: int | None = None
    try:
        qdrant = get_qdrant_client()
        result = await qdrant.count(
            collection_name=settings.qdrant_collection,
            count_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant.slug),
                    )
                ]
            ),
            exact=True,
        )
        vector_chunks = result.count
    except Exception:  # noqa: BLE001
        _log.warning(
            "usage.qdrant_count_failed tenant_id=%s slug=%s",
            str(tenant.id),
            tenant.slug,
        )

    return TenantUsageRead(
        document_count=document_count,
        product_count=product_count,
        member_count=member_count,
        vector_chunks=vector_chunks,
        messages_7d=messages_7d,
        messages_total=messages_total,
    )


@router.delete("/{tenant_id}", status_code=204, response_class=Response)
async def delete_tenant(
    tenant_id: uuid.UUID,
    body: _DeleteWorkspaceBody,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    """Hard-delete the workspace.

    Order of operations:
    1. Verify ``confirm_name`` matches ``tenant.name`` exactly (400).
    2. Delete all Qdrant points for this tenant by slug filter — FAIL HARD
       on Qdrant error (no orphan vectors).
    3. Best-effort avatar object delete.
    4. ``db.delete(tenant)`` — Postgres FK CASCADE handles all children.

    A member (non-owner) receives 403 from ``require_owner``.
    """
    _check_path_matches_header(tenant, tenant_id)

    if body.confirm_name != tenant.name:
        raise HTTPException(status_code=400, detail="confirm_name_mismatch")

    # Step 1 — purge Qdrant vectors. FAIL HARD — do not let a partial
    # delete leave orphan vectors under a potentially reused slug.
    tenant_slug = tenant.slug
    qdrant = get_qdrant_client()
    await qdrant.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_slug),
                    )
                ]
            )
        ),
        wait=True,
    )
    _log.info(
        "tenant.delete.qdrant_purged tenant_id=%s slug=%s",
        str(tenant.id),
        tenant_slug,
    )

    # Step 2 — best-effort avatar cleanup (non-fatal)
    avatar_key = _tenant_avatar_key(tenant)
    try:
        await object_store.delete_object(
            bucket=settings.minio_bucket_avatars, key=avatar_key
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "tenant.delete.avatar_cleanup_failed tenant_id=%s detail=%s",
            str(tenant.id),
            exc,
        )

    # Step 3 — delete the Postgres row; FK CASCADE removes all children.
    await db.delete(tenant)
    await db.commit()

    _log.info(
        "tenant.deleted tenant_id=%s actor=%s slug=%s",
        str(tenant_id),
        str(user.id),
        tenant_slug,
    )
    return Response(status_code=204)
