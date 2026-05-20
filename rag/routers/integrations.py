"""Integrations router — CRUD + test-fire + Messenger token management."""

from __future__ import annotations

import json
import os
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import messenger_overlay
from database import DB_PATH, now_iso
from events import EVENT_NAMES
from integrations.dispatcher import fire_test
from integrations.providers import PROVIDERS
from routers.deps import require_auth

router = APIRouter(tags=["integrations"], dependencies=[Depends(require_auth)])

VALID_TYPES = frozenset(PROVIDERS.keys())


class IntegrationCreate(BaseModel):
    type: str
    name: str = Field(..., min_length=1, max_length=80)
    config: dict[str, Any]
    events: list[str] = Field(default_factory=list)
    enabled: bool = True


class IntegrationPatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    events: list[str] | None = None
    enabled: bool | None = None


def _redact(itype: str, config: dict[str, Any]) -> dict[str, Any]:
    provider = PROVIDERS.get(itype)
    if provider is None or not hasattr(provider, "redact"):
        return config
    try:
        return provider.redact(config)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return config


def _validate_type(t: str) -> None:
    if t not in VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown type {t!r}. Valid: {sorted(VALID_TYPES)}",
        )


def _validate_events(events: list[str]) -> None:
    bad = [e for e in events if e not in EVENT_NAMES and e != "nexus.test"]
    if bad:
        raise HTTPException(
            status_code=400, detail=f"Unknown events: {bad}. Valid: {list(EVENT_NAMES)}"
        )


def _row_to_dict(r: aiosqlite.Row) -> dict[str, Any]:
    try:
        config = json.loads(r["config_json"])
    except json.JSONDecodeError:
        config = {}
    return {
        "id": r["id"],
        "type": r["type"],
        "name": r["name"],
        "config": _redact(r["type"], config),
        "events": [e for e in (r["events_csv"] or "").split(",") if e],
        "enabled": bool(r["enabled"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "last_fired_at": r["last_fired_at"],
        "last_status": r["last_status"],
    }


@router.get("")
async def list_integrations() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, type, name, config_json, events_csv, enabled, created_at,
                   updated_at, last_fired_at, last_status
            FROM integrations ORDER BY id DESC
            """
        )
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/events")
async def list_events() -> dict:
    return {"events": list(EVENT_NAMES), "types": sorted(VALID_TYPES)}


# ─────────────────────────────────────────────────────────────────────────────
# Messenger token management (Phase 11)
#
# Declared BEFORE the parametric `/{integration_id}` routes below so the
# literal `/messenger` path wins the match.
# ─────────────────────────────────────────────────────────────────────────────


class MessengerPatch(BaseModel):
    verify_token: str | None = Field(default=None, min_length=16, max_length=512)
    page_access_token: str | None = Field(default=None, min_length=16, max_length=512)
    app_secret: str | None = Field(default=None, min_length=16, max_length=512)


def _public_base_url(request: Request) -> str:
    """Return the user-facing base URL for webhook display.

    Honors ``PUBLIC_BASE_URL`` env override (set in prod to the HTTPS host)
    and falls back to the request's scheme + host when running locally.
    """
    override = os.environ.get("PUBLIC_BASE_URL")
    if override:
        return override.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}"


def _messenger_payload(request: Request) -> dict[str, Any]:
    verify = messenger_overlay.current_verify_token()
    pat = messenger_overlay.current_page_access_token()
    app_secret = messenger_overlay.current_app_secret()
    return {
        "webhook_url": f"{_public_base_url(request)}/webhook/messenger/inbound",
        "verify_token": verify,
        "verify_token_present": verify is not None,
        "page_access_token_masked": messenger_overlay.mask_page_access_token(pat),
        "page_access_token_present": pat is not None,
        "app_secret_masked": messenger_overlay.mask_app_secret(app_secret),
        "app_secret_present": app_secret is not None,
    }


@router.get("/messenger")
async def get_messenger(request: Request) -> dict[str, Any]:
    return _messenger_payload(request)


@router.post("/messenger/rotate-verify-token")
async def rotate_messenger_verify_token(request: Request) -> dict[str, Any]:
    messenger_overlay.rotate_verify_token()
    return _messenger_payload(request)


@router.patch("/messenger")
async def patch_messenger(body: MessengerPatch, request: Request) -> dict[str, Any]:
    if (
        body.verify_token is None
        and body.page_access_token is None
        and body.app_secret is None
    ):
        raise HTTPException(status_code=422, detail="No fields to update")
    try:
        if body.verify_token is not None:
            messenger_overlay.set_verify_token(body.verify_token)
        if body.page_access_token is not None:
            messenger_overlay.set_page_access_token(body.page_access_token)
        if body.app_secret is not None:
            messenger_overlay.set_app_secret(body.app_secret)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _messenger_payload(request)


@router.post("", status_code=201)
async def create_integration(body: IntegrationCreate) -> dict:
    _validate_type(body.type)
    _validate_events(body.events)
    ts = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO integrations
                (type, name, config_json, events_csv, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.type,
                body.name,
                json.dumps(body.config),
                ",".join(body.events),
                1 if body.enabled else 0,
                ts,
                ts,
            ),
        )
        await db.commit()
        new_id = cur.lastrowid
        db.row_factory = aiosqlite.Row
        cur2 = await db.execute(
            """
            SELECT id, type, name, config_json, events_csv, enabled, created_at,
                   updated_at, last_fired_at, last_status
            FROM integrations WHERE id = ?
            """,
            (new_id,),
        )
        row = await cur2.fetchone()
    assert row is not None
    return _row_to_dict(row)


@router.patch("/{integration_id}")
async def update_integration(integration_id: int, body: IntegrationPatch) -> dict:
    if body.events is not None:
        _validate_events(body.events)

    sets: list[str] = []
    args: list[Any] = []
    if body.name is not None:
        sets.append("name = ?")
        args.append(body.name)
    if body.config is not None:
        sets.append("config_json = ?")
        args.append(json.dumps(body.config))
    if body.events is not None:
        sets.append("events_csv = ?")
        args.append(",".join(body.events))
    if body.enabled is not None:
        sets.append("enabled = ?")
        args.append(1 if body.enabled else 0)
    if not sets:
        raise HTTPException(status_code=422, detail="No fields to update")
    sets.append("updated_at = ?")
    args.append(now_iso())
    args.append(integration_id)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            f"UPDATE integrations SET {', '.join(sets)} WHERE id = ?", args
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Integration not found")
        db.row_factory = aiosqlite.Row
        cur2 = await db.execute(
            """
            SELECT id, type, name, config_json, events_csv, enabled, created_at,
                   updated_at, last_fired_at, last_status
            FROM integrations WHERE id = ?
            """,
            (integration_id,),
        )
        row = await cur2.fetchone()
    assert row is not None
    return _row_to_dict(row)


@router.delete("/{integration_id}", status_code=204, response_class=Response)
async def delete_integration(integration_id: int) -> Response:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Integration not found")
    return Response(status_code=204)


@router.post("/{integration_id}/test")
async def test_integration(integration_id: int) -> dict:
    status, body = await fire_test(integration_id)
    return {"status": status, "body": body, "ok": 200 <= status < 300}
