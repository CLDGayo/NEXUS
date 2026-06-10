"""Phase 29 — tenant CRUD endpoints.

* ``POST /api/tenants``  — create a tenant. Caller becomes ``owner``.
* ``GET  /api/tenants``  — list tenants the caller belongs to (with role).
* ``GET  /api/tenants/{id}`` — single-tenant detail, gated by membership.

Phase 50 — workspace member management (manager-gated):

* ``GET    /api/tenants/{id}/members``           — list members with roles.
* ``PATCH  /api/tenants/{id}/members/{user_id}`` — change a member's role.
* ``DELETE /api/tenants/{id}/members/{user_id}`` — remove a member.

Slug uniqueness collisions surface as 409. Empty / whitespace-only names
are rejected at the schema layer (``min_length=1``).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import (
    MemberRead,
    MemberRoleUpdate,
    TenantCreate,
    TenantRead,
    current_active_user,
    list_tenants_for_user,
    slugify_tenant_name,
)
from rag.database.engine import get_async_session
from rag.database.models import Tenant, TenantUser, User
from routers.deps import require_manager

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


@router.delete("/{tenant_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> None:
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
