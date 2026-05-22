"""Authentication — legacy password login (Phase 27 transitional shim).

Phase 27 Part 1.1 — the legacy ``POST /api/auth/login`` endpoint still
accepts the single ``NEXUS_PASSWORD`` the SPA has always sent, but instead
of minting an old-style ``sub="admin"`` JWT it now:

1. Verifies the password (``auth_overlay.verify_password``).
2. Looks up the designated superuser row in ``app.users``.
3. If found, asks fastapi-users' ``JWTStrategy`` to mint a token bound to
   that user's UUID. The SPA receives a token that satisfies
   ``current_active_user`` on ``/api/chat/*``.
4. If no superuser is provisioned yet (fresh deploy), returns 503 with a
   clear error so the operator knows to run the bootstrap SQL.

The /api/auth/jwt/login (fastapi-users) and /api/auth/register routes mounted
in ``rag/main.py`` remain the canonical multi-user surface. This shim only
exists to keep the single-password SPA flow working until Part 2 cuts it
over to ``/api/auth/jwt/login``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from auth_overlay import verify_password

from rag.auth import get_jwt_strategy
from rag.database.engine import get_async_session
from rag.database.models import User

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


async def _load_designated_superuser(db: AsyncSession) -> User | None:
    """Return the first active superuser row, or ``None`` if none exists.

    Extracted into a module-level helper so tests can monkeypatch it
    without standing up a real Postgres connection.
    """
    stmt = (
        select(User)
        .where(User.is_superuser.is_(True))
        .where(User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_async_session),
) -> LoginResponse:
    if not verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")

    try:
        superuser = await _load_designated_superuser(db)
    except SQLAlchemyError as exc:  # database unreachable / schema missing
        raise HTTPException(
            status_code=503,
            detail=(
                "Auth database unavailable — run `alembic upgrade head` "
                "and provision a superuser before retrying."
            ),
        ) from exc

    if superuser is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin account not provisioned. Register a user via "
                "POST /api/auth/register, then run `UPDATE app.users SET "
                "is_superuser = true WHERE email = '...'`."
            ),
        )

    strategy = get_jwt_strategy()
    token = await strategy.write_token(superuser)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=strategy.lifetime_seconds or 3600
    )
    return LoginResponse(token=token, expires_at=expires_at.isoformat())
