"""Phase 29 — strict-tenancy guard.

Every data-bearing route depends on ``get_current_tenant`` to:

1. Pull the active tenant id from the ``X-Tenant-ID`` request header.
2. Verify the authenticated user is a member of that tenant via
   ``app.tenant_users``.
3. Stash both id and slug on ``request.state`` for downstream observability
   spans + log correlation.
4. Return the resolved ``Tenant`` ORM row so handlers can read ``.slug``
   for SQLite + Qdrant payload filtering.

A missing header is a hard 400 (we never silently pick a tenant — that
would re-introduce the cross-tenant leak Phase 29 closes). Membership
failures surface as 403, not 404, so the caller knows the tenant exists
but is gated.
"""

from __future__ import annotations

import re
import uuid

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth.config import current_active_user
from rag.auth.schemas import TenantRead
from rag.database.engine import get_async_session
from rag.database.models import Tenant, TenantUser, User

# Lowercase ASCII letters, digits, hyphens. Used to normalize user input
# into a Qdrant- and URL-safe handle.
_SLUG_SAFE_RE = re.compile(r"[^a-z0-9-]+")
_SLUG_HYPHEN_COLLAPSE_RE = re.compile(r"-{2,}")
_SLUG_MAX_LENGTH = 120


def slugify_tenant_name(name: str) -> str:
    """Lowercase, ASCII-only, hyphen-separated form of ``name``.

    Empty input collapses to the literal ``tenant`` so we never emit an
    empty slug (downstream code treats slug as a non-empty key). Length is
    clamped to ``_SLUG_MAX_LENGTH`` matching the column constraint.
    """

    candidate = name.strip().lower()
    candidate = _SLUG_SAFE_RE.sub("-", candidate)
    candidate = _SLUG_HYPHEN_COLLAPSE_RE.sub("-", candidate).strip("-")
    if not candidate:
        candidate = "tenant"
    return candidate[:_SLUG_MAX_LENGTH]


async def get_current_tenant(
    request: Request,
    x_tenant_id: uuid.UUID | None = Header(default=None, alias="X-Tenant-ID"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> Tenant:
    """Resolve + authorise the active tenant for this request."""

    if x_tenant_id is None:
        raise HTTPException(status_code=400, detail="missing X-Tenant-ID header")

    link = await db.get(TenantUser, (x_tenant_id, user.id))
    if link is None:
        # Treat unknown tenants the same as forbidden ones — leaks no info
        # about which tenant ids exist on the platform.
        raise HTTPException(status_code=403, detail="tenant access denied")

    tenant = await db.get(Tenant, x_tenant_id)
    if tenant is None:
        # The TenantUser row exists but the Tenant doesn't — should be
        # impossible under FK constraints. Treat as 404 so this surfaces
        # clearly in logs if it ever happens.
        raise HTTPException(status_code=404, detail="tenant not found")

    # Phase 52 — archived workspace guard. Data-bearing routes (anything
    # outside /api/tenants) return 403 "workspace_archived" so active
    # members cannot interact with a suspended workspace. The /api/tenants
    # prefix is exempted so owners can view/unarchive/transfer/delete the
    # archived workspace without having to bypass the guard themselves.
    if tenant.archived_at is not None and not request.url.path.startswith(
        "/api/tenants"
    ):
        raise HTTPException(status_code=403, detail="workspace_archived")

    # Stash on request.state for observability hooks (OTEL spans + Langfuse
    # traces read these in Phase 5+).
    request.state.tenant_id = tenant.id
    request.state.tenant_slug = tenant.slug
    request.state.tenant_role = link.role
    return tenant


async def list_tenants_for_user(db: AsyncSession, user: User) -> list[TenantRead]:
    """Return every tenant the user belongs to, annotated with their role.

    Used by ``GET /api/tenants`` so the SPA can render the workspace
    switcher. Ordered by tenant ``created_at`` ascending so the default
    Hunter tenant appears first for legacy users.
    """

    # Phase 50 — member_count powers the workspace master list. The
    # correlated scalar subquery counts every membership row per tenant
    # (not just the caller's), one round-trip total.
    member_count_sq = (
        select(func.count())
        .select_from(TenantUser)
        .where(TenantUser.tenant_id == Tenant.id)
        .correlate(Tenant)
        .scalar_subquery()
    )
    stmt = (
        select(Tenant, TenantUser.role, member_count_sq)
        .join(TenantUser, TenantUser.tenant_id == Tenant.id)
        .where(TenantUser.user_id == user.id)
        .order_by(Tenant.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        TenantRead(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            created_at=tenant.created_at,
            role=role,
            member_count=member_count,
            avatar_url=tenant.avatar_url,
            archived_at=tenant.archived_at,
            preferred_language=tenant.preferred_language,
        )
        for tenant, role, member_count in rows
    ]
