"""Phase 56 — domain auto-join admin (manager-gated approve/reject).

When an OAuth user's verified email domain matches a ``tenant.domain`` they get
a pending ``DomainJoinRequest`` instead of a brand-new workspace. A manager
(owner/admin) of that tenant approves or rejects here; approval mints the
``TenantUser`` membership.

    GET   /api/tenants/{tenant_id}/join-requests              list pending
    POST  /api/tenants/{tenant_id}/join-requests/{id}/approve grant membership
    POST  /api/tenants/{tenant_id}/join-requests/{id}/reject  decline
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_active_user
from rag.database.engine import get_async_session
from rag.database.models import DomainJoinRequest, Tenant, TenantUser, User
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["domain-join"])


def _serialize(req: DomainJoinRequest, *, email: str | None = None) -> dict:
    return {
        "id": str(req.id),
        "tenant_id": str(req.tenant_id),
        "user_id": str(req.user_id),
        "user_email": email,
        "email_domain": req.email_domain,
        "status": req.status,
        "created_at": req.created_at.isoformat(),
    }


@router.get("/{tenant_id}/join-requests")
async def list_join_requests(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict]:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    rows = (
        await db.execute(
            select(DomainJoinRequest, User.email)
            .join(User, User.id == DomainJoinRequest.user_id)
            .where(
                DomainJoinRequest.tenant_id == tenant.id,
                DomainJoinRequest.status == "pending",
            )
            .order_by(DomainJoinRequest.created_at.desc())
        )
    ).all()
    return [_serialize(req, email=email) for req, email in rows]


async def _load_pending(
    db: AsyncSession, tenant: Tenant, request_id: uuid.UUID
) -> DomainJoinRequest:
    req = (
        await db.execute(
            select(DomainJoinRequest)
            .where(
                DomainJoinRequest.id == request_id,
                DomainJoinRequest.tenant_id == tenant.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="join_request_not_found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="join_request_decided")
    return req


@router.post("/{tenant_id}/join-requests/{request_id}/approve", status_code=200)
async def approve_join_request(
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    req = await _load_pending(db, tenant, request_id)

    already = await db.get(TenantUser, (tenant.id, req.user_id))
    if already is None:
        db.add(TenantUser(tenant_id=tenant.id, user_id=req.user_id, role="member"))
    req.status = "approved"
    req.decided_by = user.id
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    _log.info(
        "domain_join.approved tenant=%s user=%s by=%s",
        tenant.id,
        req.user_id,
        user.id,
    )
    return {
        "status": "approved",
        "tenant_id": str(tenant.id),
        "user_id": str(req.user_id),
    }


@router.post("/{tenant_id}/join-requests/{request_id}/reject", status_code=200)
async def reject_join_request(
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    req = await _load_pending(db, tenant, request_id)
    req.status = "rejected"
    req.decided_by = user.id
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    _log.info("domain_join.rejected tenant=%s user=%s", tenant.id, req.user_id)
    return {"status": "rejected"}
