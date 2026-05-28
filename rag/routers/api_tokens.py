"""API tokens router — create/list/revoke programmatic Bearer tokens.

Phase 30.1 — backed by ``app.api_tokens`` via the SQLAlchemy 2.0 async
ORM. Token ids are UUIDs (changed from the legacy SQLite
``INTEGER AUTOINCREMENT``); the frontend now consumes them as strings.

Phase 31 — every endpoint is gated by ``require_owner`` and every query
filters by ``ApiToken.tenant_id == tenant.id``. Tokens are now owned by
exactly one tenant; an owner of workspace A cannot see, create, or
revoke tokens minted under workspace B.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_active_user
from rag.database.engine import get_async_session
from rag.database.models import ApiToken, Tenant, User
from routers.deps import TOKEN_PREFIX, VALID_SCOPES, require_owner

router = APIRouter(tags=["api-tokens"])


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    scopes: list[str] = Field(..., min_length=1)


def _serialize(token: ApiToken) -> dict:
    return {
        "id": str(token.id),
        "name": token.name,
        "prefix": token.prefix,
        "scopes": [s for s in (token.scopes_csv or "").split(",") if s],
        "created_at": (
            token.created_at.isoformat() if token.created_at else None
        ),
        "last_used_at": (
            token.last_used_at.isoformat() if token.last_used_at else None
        ),
        "revoked_at": (
            token.revoked_at.isoformat() if token.revoked_at else None
        ),
        "active": token.revoked_at is None,
    }


@router.get("")
async def list_tokens(
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict]:
    stmt = (
        select(ApiToken)
        .where(ApiToken.tenant_id == tenant.id)
        .order_by(ApiToken.created_at.desc())
    )
    tokens = (await db.execute(stmt)).scalars().all()
    return [_serialize(t) for t in tokens]


@router.post("", status_code=201)
async def create_token(
    body: TokenCreate,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    unknown = [s for s in body.scopes if s not in VALID_SCOPES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scopes: {unknown}. Valid: {sorted(VALID_SCOPES)}",
        )

    raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(36)}"
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = raw[: len(TOKEN_PREFIX) + 8]
    scopes_csv = ",".join(sorted(set(body.scopes)))

    token = ApiToken(
        id=uuid.uuid4(),
        name=body.name,
        token_hash=token_hash,
        prefix=prefix,
        scopes_csv=scopes_csv,
        user_id=user.id,
        tenant_id=tenant.id,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    return {
        "id": str(token.id),
        "name": token.name,
        "scopes": sorted(set(body.scopes)),
        "prefix": prefix,
        "token": raw,
        "warning": "Save this token now. It will not be shown again.",
    }


@router.delete("/{token_id}", status_code=204, response_class=Response)
async def revoke_token(
    token_id: uuid.UUID,
    tenant: Tenant = Depends(require_owner),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    stmt = select(ApiToken).where(
        ApiToken.id == token_id,
        ApiToken.tenant_id == tenant.id,
    )
    token = (await db.execute(stmt)).scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        raise HTTPException(
            status_code=404,
            detail="Token not found or already revoked",
        )
    token.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)
