"""Phase 29 — tenant CRUD endpoints.

* ``POST /api/tenants``  — create a tenant. Caller becomes ``owner``.
* ``GET  /api/tenants``  — list tenants the caller belongs to (with role).
* ``GET  /api/tenants/{id}`` — single-tenant detail, gated by membership.

Slug uniqueness collisions surface as 409. Empty / whitespace-only names
are rejected at the schema layer (``min_length=1``).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import (
    TenantCreate,
    TenantRead,
    current_active_user,
    list_tenants_for_user,
    slugify_tenant_name,
)
from rag.database.engine import get_async_session
from rag.database.models import Tenant, TenantUser, User
from routers.deps import require_owner

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

    db.add(
        TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner")
    )
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
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> TenantRead:
    """Return a single tenant. Phase 31 gated by ``require_owner`` — only
    owners of the active workspace can read its detail payload. The path
    id must match the ``X-Tenant-ID`` header so a curl that swaps either
    one is rejected before a row is read."""

    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )

    # require_owner already verified the role; re-read for the response
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
    )
