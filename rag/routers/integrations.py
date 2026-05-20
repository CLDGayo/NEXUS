"""Integrations router — CRUD + test-fire."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

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
