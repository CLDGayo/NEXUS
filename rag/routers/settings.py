"""Settings router — KV config GET/PATCH, password change, JWT rotate.

All endpoints require JWT auth. Settings keys are validated against the
allow-list in `settings_service.SETTING_KEYS`.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import settings_service
from auth_overlay import rotate_jwt_secret, set_password, verify_password
from routers.deps import require_auth

router = APIRouter(tags=["settings"], dependencies=[Depends(require_auth)])


class PasswordChange(BaseModel):
    old: str = Field(..., min_length=1)
    new: str = Field(..., min_length=8)


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


@router.post("/password", status_code=204)
async def change_password(body: PasswordChange) -> None:
    if not verify_password(body.old):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    try:
        set_password(body.new)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rotate-jwt")
async def rotate_jwt() -> dict:
    """Rotate the JWT signing secret. All existing tokens are invalidated."""
    rotate_jwt_secret()
    return {"ok": True, "message": "JWT secret rotated. Please log in again."}
