"""Phase 51 — Workspace invite & join-code endpoints.

Tenant-gated routes (require_manager):
    POST   /api/tenants/{tenant_id}/invites          create invite
    GET    /api/tenants/{tenant_id}/invites          list pending invites
    POST   /api/tenants/{tenant_id}/invites/{id}/resend   re-fire n8n email
    DELETE /api/tenants/{tenant_id}/invites/{id}    revoke

Public (authed user, no tenant gate):
    POST   /api/invites/accept   consume token → join workspace
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_active_user
from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import Tenant, TenantInvite, TenantUser, User
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

_INVITE_TTL_DAYS = 7

router = APIRouter(prefix="/api/tenants", tags=["invites"])
public_router = APIRouter(prefix="/api/invites", tags=["invites"])


# ---------- schemas -----------------------------------------------------------


class InviteCreate(BaseModel):
    email: EmailStr | None = None
    role: str = Field(default="member", pattern="^(admin|member)$")


class InviteRead(BaseModel):
    id: uuid.UUID
    email: str | None
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    invite_link: str


class AcceptInvite(BaseModel):
    token: str


# ---------- helpers -----------------------------------------------------------


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _invite_link(raw: str) -> str:
    base = (settings.nexus_public_base_url or "").rstrip("/")
    return f"{base}/join?token={raw}"


def _serialize(invite: TenantInvite, raw_token: str | None = None) -> dict:
    link = _invite_link(raw_token) if raw_token else ""
    return {
        "id": str(invite.id),
        "email": invite.email,
        "role": invite.role,
        "status": invite.status,
        "expires_at": invite.expires_at.isoformat(),
        "created_at": invite.created_at.isoformat(),
        "invite_link": link,
    }


async def _fire_n8n_invite(
    email: str,
    workspace_name: str,
    invite_link: str,
    role: str,
) -> None:
    webhook_url = settings.n8n_webhook_invite_url
    if not webhook_url:
        _log.info("invites.n8n: N8N_WEBHOOK_INVITE_URL unset — skipping email dispatch")
        return
    payload = {
        "email": email,
        "workspace_name": workspace_name,
        "invite_link": invite_link,
        "role": role,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        ) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        _log.info("invites.n8n: sent invite email to %s via n8n", email)
    except httpx.HTTPStatusError as exc:
        _log.error(
            "invites.n8n: n8n returned %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
    except httpx.TimeoutException:
        _log.error("invites.n8n: webhook timed out for %s", email)
    except Exception as exc:  # noqa: BLE001
        _log.error("invites.n8n: unexpected error for %s: %s", email, exc)


@dataclass(frozen=True)
class InviteOutcome:
    """Result of consuming an invite. ``status`` is one of:
    ``ok`` (joined), ``already_member``, ``not_found``, ``already_used``,
    ``expired``.
    """

    status: str
    tenant_id: uuid.UUID | None = None
    role: str | None = None


async def resolve_and_apply_invite(
    db: AsyncSession, user: User, raw_token: str
) -> InviteOutcome:
    """Consume a pending invite for ``user`` and apply membership.

    Mutates the session (adds the ``TenantUser`` row, marks the invite
    accepted) but does NOT commit — the caller owns the transaction boundary
    so this composes inside the OAuth callback's single commit. Returns an
    outcome instead of raising for the invalid-token cases so the OAuth path
    can fall through to other tenant-resolution branches.
    """

    token_hash = _token_hash(raw_token)
    invite = (
        await db.execute(
            select(TenantInvite).where(TenantInvite.token_hash == token_hash)
        )
    ).scalar_one_or_none()

    if invite is None:
        return InviteOutcome("not_found")
    if invite.status != "pending":
        return InviteOutcome("already_used", tenant_id=invite.tenant_id)
    if invite.expires_at < datetime.now(timezone.utc):
        return InviteOutcome("expired", tenant_id=invite.tenant_id)

    existing = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == invite.tenant_id,
                TenantUser.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        invite.status = "accepted"
        return InviteOutcome(
            "already_member", tenant_id=invite.tenant_id, role=existing.role
        )

    db.add(
        TenantUser(
            tenant_id=invite.tenant_id, user_id=user.id, role=invite.role
        )
    )
    invite.status = "accepted"
    return InviteOutcome("ok", tenant_id=invite.tenant_id, role=invite.role)


# ---------- tenant-gated routes -----------------------------------------------


@router.post("/{tenant_id}/invites", status_code=201)
async def create_invite(
    tenant_id: uuid.UUID,
    body: InviteCreate,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    invite = TenantInvite(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=body.email,
        role=body.role,
        token_hash=_token_hash(raw),
        invited_by=user.id,
        status="pending",
        expires_at=now + timedelta(days=_INVITE_TTL_DAYS),
        created_at=now,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    link = _invite_link(raw)
    if body.email:
        await _fire_n8n_invite(
            email=body.email,
            workspace_name=tenant.name,
            invite_link=link,
            role=body.role,
        )

    return {**_serialize(invite, raw), "invite_link": link}


@router.get("/{tenant_id}/invites")
async def list_invites(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict]:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    stmt = (
        select(TenantInvite)
        .where(
            TenantInvite.tenant_id == tenant.id,
            TenantInvite.status == "pending",
        )
        .order_by(TenantInvite.created_at.desc())
    )
    invites = (await db.execute(stmt)).scalars().all()
    return [_serialize(inv) for inv in invites]


@router.post("/{tenant_id}/invites/{invite_id}/resend", status_code=200)
async def resend_invite(
    tenant_id: uuid.UUID,
    invite_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    stmt = select(TenantInvite).where(
        TenantInvite.id == invite_id,
        TenantInvite.tenant_id == tenant.id,
    )
    invite = (await db.execute(stmt)).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="invite_not_found")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="invite_not_pending")
    if not invite.email:
        raise HTTPException(status_code=400, detail="open_code_no_email")

    # Resend fires n8n but the token itself is unchanged.
    # We can't reconstruct the raw token from the hash, so we generate a new
    # one and replace the hash — effectively a token rotation on resend.
    raw = secrets.token_urlsafe(32)
    invite.token_hash = _token_hash(raw)
    invite.expires_at = datetime.now(timezone.utc) + timedelta(days=_INVITE_TTL_DAYS)
    await db.commit()
    await db.refresh(invite)

    link = _invite_link(raw)
    await _fire_n8n_invite(
        email=invite.email,
        workspace_name=tenant.name,
        invite_link=link,
        role=invite.role,
    )
    return {**_serialize(invite, raw), "invite_link": link}


@router.delete(
    "/{tenant_id}/invites/{invite_id}", status_code=204, response_class=Response
)
async def revoke_invite(
    tenant_id: uuid.UUID,
    invite_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")

    stmt = select(TenantInvite).where(
        TenantInvite.id == invite_id,
        TenantInvite.tenant_id == tenant.id,
    )
    invite = (await db.execute(stmt)).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="invite_not_found")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="invite_not_pending")

    invite.status = "revoked"
    await db.commit()
    return Response(status_code=204)


# ---------- public accept route (no tenant gate) ------------------------------


@public_router.post("/accept", status_code=200)
async def accept_invite(
    body: AcceptInvite,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    outcome = await resolve_and_apply_invite(db, user, body.token)

    if outcome.status == "not_found":
        raise HTTPException(status_code=404, detail="invite_not_found")
    if outcome.status == "already_used":
        raise HTTPException(status_code=409, detail="invite_already_used")
    if outcome.status == "expired":
        raise HTTPException(status_code=410, detail="invite_expired")

    await db.commit()

    if outcome.status == "already_member":
        return {"tenant_id": str(outcome.tenant_id), "role": outcome.role}

    tenant_stmt = select(Tenant).where(Tenant.id == outcome.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()

    _log.info(
        "invites.accept: user=%s joined tenant=%s role=%s",
        user.id,
        outcome.tenant_id,
        outcome.role,
    )
    return {
        "tenant_id": str(outcome.tenant_id),
        "tenant_name": tenant.name if tenant else None,
        "tenant_slug": tenant.slug if tenant else None,
        "role": outcome.role,
    }
