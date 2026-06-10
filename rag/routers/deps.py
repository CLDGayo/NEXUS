"""Shared FastAPI dependencies — JWT-only, JWT-or-API-token, and Phase 31
``require_owner`` (tenant-membership + ``role == 'owner'``)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from auth_overlay import current_jwt_secret

from rag.auth.config import current_active_user
from rag.auth.tenant import get_current_tenant
from rag.config import settings
from rag.database.engine import get_sessionmaker
from rag.database.models import ApiToken, Tenant, User

_bearer = HTTPBearer(auto_error=False)

TOKEN_PREFIX = "nxs_"

VALID_SCOPES = frozenset(
    {
        "chat:read",
        "chat:write",
        "documents:read",
        "documents:write",
        "dashboard:read",
    }
)

# Phase 27 Part 1.1 — fastapi-users mints JWTs with this audience claim.
# python-jose's `jwt.decode` rejects tokens whose `aud` doesn't match the
# `audience=` kwarg, so the legacy deps must opt in to validate them.
_FASTAPI_USERS_AUDIENCE = "fastapi-users:auth"


def _try_jwt(raw: str) -> dict | None:
    """Decode either a fastapi-users JWT (Phase 27 shim output) or the
    legacy admin JWT. Returning the first that verifies preserves
    backward compatibility for any tokens already cached in clients."""
    # New tokens minted by the Phase 27 shim / fastapi-users login.
    nexus_secret = settings.nexus_jwt_secret
    if nexus_secret:
        try:
            return jwt.decode(
                raw,
                nexus_secret,
                algorithms=["HS256"],
                audience=_FASTAPI_USERS_AUDIENCE,
            )
        except JWTError:
            pass
    # Legacy admin JWT (sub="admin", no audience).
    try:
        return jwt.decode(raw, current_jwt_secret(), algorithms=["HS256"])
    except JWTError:
        return None


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Strict JWT-only auth. Used for admin endpoints (settings, integrations)."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if _try_jwt(credentials.credentials) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def require_owner(
    request: Request,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """Phase 31 — Owner-role RBAC gate for admin-class endpoints.

    ``get_current_tenant`` already validated tenant membership and stashed
    ``request.state.tenant_role``; we only need to confirm the role is
    ``owner`` before letting the handler run. Returns the resolved tenant
    so route handlers can chain ``Depends(require_owner)`` and read
    ``tenant.id`` / ``tenant.slug`` without re-resolving.

    A non-owner member receives 403 ``owner_role_required`` so the
    frontend can show a precise toast instead of a generic ``Forbidden``.
    """

    _ = user  # auth side-effect only — get_current_tenant did membership check.
    role = getattr(request.state, "tenant_role", None)
    if role != "owner":
        raise HTTPException(status_code=403, detail="owner_role_required")
    return tenant


async def require_manager(
    request: Request,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """Phase 50 — manager-class RBAC gate (``owner`` OR ``admin``).

    Mirrors ``require_owner`` but accepts both manager tiers. Used by
    member-management, settings, ai-settings, and integration endpoints
    where Admins are allowed but plain Members are not. Owner-only
    operations (archive, transfer, hard-delete) keep ``require_owner``.

    A plain member receives 403 ``manager_role_required`` so the frontend
    can show a precise toast.
    """

    _ = user  # auth side-effect only — get_current_tenant did membership check.
    role = getattr(request.state, "tenant_role", None)
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="manager_role_required")
    return tenant


async def _lookup_token(raw: str, scope: str) -> dict:
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        token = (
            await db.execute(select(ApiToken).where(ApiToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if token is None or token.revoked_at is not None:
            raise HTTPException(status_code=401, detail="Invalid or revoked token")
        scopes = {s.strip() for s in (token.scopes_csv or "").split(",") if s.strip()}
        if scope not in scopes:
            raise HTTPException(status_code=403, detail=f"Token missing scope: {scope}")
        token.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "sub": f"token:{token.id}",
            "via": "token",
            "name": token.name,
        }


def require_auth_or_token(scope: str) -> Callable[..., object]:
    """Factory: returns a FastAPI dependency that accepts JWT or scoped API token."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown scope: {scope}")

    async def _dep(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> dict:
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")
        raw = credentials.credentials

        # JWT path — full access, no scope check.
        decoded = _try_jwt(raw)
        if decoded is not None:
            return {"sub": decoded.get("sub", "admin"), "via": "jwt"}

        # API token path
        if not raw.startswith(TOKEN_PREFIX):
            raise HTTPException(status_code=401, detail="Invalid bearer")
        return await _lookup_token(raw, scope)

    return _dep
