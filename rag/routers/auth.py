"""Authentication — legacy password login is removed (Phase 27 Part 2).

The transitional shim that accepted a single ``NEXUS_PASSWORD`` and minted a
fastapi-users-compatible JWT has been retired. The canonical login surface is
``POST /api/auth/jwt/login`` (OAuth2PasswordRequestForm — ``username`` +
``password`` as ``application/x-www-form-urlencoded``), mounted by
``rag.main`` via ``fastapi_users.get_auth_router(...)``.

We keep the ``POST /api/auth/login`` route registered so any stale SPA build
in a browser cache receives a deterministic ``410 Gone`` with a pointer at
the new endpoint instead of a confusing ``404``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["auth"])


@router.post("/login", status_code=410)
async def login_removed() -> None:
    raise HTTPException(
        status_code=410,
        detail="Removed. Use POST /api/auth/jwt/login.",
    )
