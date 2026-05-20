"""API tokens router — create/list/revoke programmatic Bearer tokens."""

from __future__ import annotations

import hashlib
import secrets

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from database import DB_PATH, now_iso
from routers.deps import TOKEN_PREFIX, VALID_SCOPES, require_auth

router = APIRouter(tags=["api-tokens"], dependencies=[Depends(require_auth)])


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    scopes: list[str] = Field(..., min_length=1)


@router.get("")
async def list_tokens() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, name, prefix, scopes_csv, created_at, last_used_at, revoked_at
            FROM api_tokens
            ORDER BY created_at DESC
            """
        )
        rows = await cur.fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "prefix": r["prefix"],
            "scopes": [s for s in (r["scopes_csv"] or "").split(",") if s],
            "created_at": r["created_at"],
            "last_used_at": r["last_used_at"],
            "revoked_at": r["revoked_at"],
            "active": r["revoked_at"] is None,
        }
        for r in rows
    ]


@router.post("", status_code=201)
async def create_token(body: TokenCreate) -> dict:
    unknown = [s for s in body.scopes if s not in VALID_SCOPES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scopes: {unknown}. Valid: {sorted(VALID_SCOPES)}",
        )

    raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(36)}"
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = raw[: len(TOKEN_PREFIX) + 8]

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO api_tokens (name, token_hash, prefix, scopes_csv, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (body.name, token_hash, prefix, ",".join(sorted(set(body.scopes))), now_iso()),
        )
        await db.commit()
        token_id = cur.lastrowid

    return {
        "id": token_id,
        "name": body.name,
        "scopes": sorted(set(body.scopes)),
        "prefix": prefix,
        "token": raw,
        "warning": "Save this token now. It will not be shown again.",
    }


@router.delete("/{token_id}", status_code=204, response_class=Response)
async def revoke_token(token_id: int) -> Response:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now_iso(), token_id),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Token not found or already revoked")
    return Response(status_code=204)
