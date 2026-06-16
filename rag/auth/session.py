"""Phase 56 — rotating refresh-token session layer.

The access token stays the existing 1h fastapi-users bearer JWT (so every
current route + ``get_current_tenant`` keeps working unchanged). This module
adds a *refresh* layer on top:

    * a long-lived (``refresh_token_ttl_days``) opaque token delivered to the
      browser as an ``HttpOnly`` ``Secure`` ``SameSite=Lax`` cookie,
    * only the SHA-256 hash is stored (``app.refresh_tokens``),
    * every use rotates: the presented token is revoked and a fresh one
      issued, so a stolen-then-replayed token is detectable.

Endpoints:
    POST /api/auth/refresh   rotate cookie -> new access JWT (+ new cookie)
    POST /api/auth/logout    revoke cookie + clear it
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth.config import get_jwt_strategy
from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import RefreshToken, User

_log = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = "nexus_refresh"
_COOKIE_PATH = "/api/auth"

router = APIRouter(prefix="/api/auth", tags=["auth-session"])


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def issue_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Create a refresh-token row and return the raw token (shown once).

    Adds + flushes but does NOT commit — the caller owns the transaction so
    this can compose inside the OAuth callback's single commit.
    """

    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=_sha256(raw),
        expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(row)
    await db.flush()
    return raw


def set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=_COOKIE_PATH)


async def rotate_refresh_token(
    db: AsyncSession, raw: str
) -> tuple[uuid.UUID, str] | None:
    """Validate + rotate. Returns (user_id, new_raw) or None if invalid.

    The presented token is locked, revoked, and replaced atomically so a
    concurrent replay of the same token loses the race.
    """

    row = (
        await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == _sha256(raw))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None or row.revoked_at is not None or row.expires_at < _now():
        return None

    row.revoked_at = _now()
    new_raw = await issue_refresh_token(db, row.user_id)
    return row.user_id, new_raw


@router.post("/refresh")
async def refresh_session(
    response: Response,
    nexus_refresh: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if not nexus_refresh:
        raise HTTPException(status_code=401, detail="missing_refresh_cookie")

    rotated = await rotate_refresh_token(db, nexus_refresh)
    if rotated is None:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="invalid_refresh_token")

    user_id, new_raw = rotated
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="user_inactive")

    await db.commit()
    access = await get_jwt_strategy().write_token(user)
    set_refresh_cookie(response, new_raw)
    _log.info("auth.refresh.ok user=%s", user_id)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    response: Response,
    nexus_refresh: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    if nexus_refresh:
        row = (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == _sha256(nexus_refresh)
                )
            )
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()
            await db.commit()
    clear_refresh_cookie(response)
    return Response(status_code=204)
