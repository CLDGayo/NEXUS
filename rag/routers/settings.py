"""Settings router — KV config GET/PATCH, JWT rotate.

Phase 50 — KV settings require ``owner`` or ``admin`` role in the active
tenant (``X-Tenant-ID`` header validated by ``get_current_tenant``);
plain members receive 403 ``manager_role_required``. JWT rotation stays
owner-only — it invalidates every session platform-wide, which is a
security-surface operation, not workspace administration. The settings
table itself stays globally-scoped for now per the Architect's Phase 31
clarification — tenant-scoped settings are a Phase 31.1 follow-up.

Phase 28 Part 2 — the legacy ``POST /api/settings/password`` route is gone.
Password rotation now lives at ``POST /api/users/me/password`` (fastapi-users
identity, requires the current password). The overlay rotation hook used by
``auth_overlay`` is dead surface — any client still posting here gets 410.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

import settings_service
from auth_overlay import rotate_jwt_secret
from routers.deps import require_manager, require_owner

router = APIRouter(tags=["settings"], dependencies=[Depends(require_manager)])


@router.get("")
async def get_settings() -> dict:
    """Return resolved settings + static descriptions + read-only env summary."""
    values = await settings_service.get_all()
    return {
        "values": values,
        "schema": settings_service.describe(),
        "env_readonly": {
            "QDRANT_URL": os.environ.get("QDRANT_URL", ""),
            "QDRANT_COLLECTION": os.environ.get("QDRANT_COLLECTION", "nexus-vault"),
            "EMBED_MODEL": os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            "VAULT_PATH": os.environ.get("VAULT_PATH", ""),
        },
    }


@router.patch("")
async def patch_settings(payload: dict[str, Any]) -> dict:
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=422, detail="Body must be a non-empty object")

    unknown = [k for k in payload if k not in settings_service.SETTING_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"Unknown setting keys: {unknown}"
        )

    updated: dict[str, Any] = {}
    for key, value in payload.items():
        try:
            updated[key] = await settings_service.set_value(key, value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid value for {key}: {exc}"
            ) from exc
    return {"updated": updated}


@router.post("/password", status_code=410, response_class=Response)
async def change_password_removed() -> Response:
    """Phase 28 Part 2 — overlay password rotation retired.

    Returns 410 so any stale SPA build or cached integration receives a
    deterministic error instead of a confusing 404. Use the fastapi-users
    surface ``POST /api/users/me/password`` instead.
    """
    raise HTTPException(
        status_code=410,
        detail="Removed. Use POST /api/users/me/password.",
    )


@router.post("/rotate-jwt", dependencies=[Depends(require_owner)])
async def rotate_jwt() -> dict:
    """Rotate the JWT signing secret. All existing tokens are invalidated."""
    rotate_jwt_secret()
    return {"ok": True, "message": "JWT secret rotated. Please log in again."}
