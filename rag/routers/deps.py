"""Shared FastAPI dependencies — JWT-only and JWT-or-API-token auth."""

from __future__ import annotations

import hashlib
from typing import Callable

import aiosqlite
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from auth_overlay import current_jwt_secret
from database import DB_PATH, now_iso

from rag.config import settings

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


async def _lookup_token(raw: str, scope: str) -> dict:
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, scopes_csv, revoked_at FROM api_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        row = await cur.fetchone()
        if not row or row["revoked_at"] is not None:
            raise HTTPException(status_code=401, detail="Invalid or revoked token")
        scopes = {s.strip() for s in (row["scopes_csv"] or "").split(",") if s.strip()}
        if scope not in scopes:
            raise HTTPException(status_code=403, detail=f"Token missing scope: {scope}")
        await db.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        await db.commit()
    return {"sub": f"token:{row['id']}", "via": "token", "name": row["name"]}


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
