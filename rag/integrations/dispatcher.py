"""Subscribes to events; routes payloads to enabled integrations."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from database import DB_PATH, now_iso
from events import EVENT_NAMES, bus

from .providers import PROVIDERS

logger = logging.getLogger(__name__)


async def _load_enabled_for(event: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, type, name, config_json, events_csv
            FROM integrations
            WHERE enabled = 1
            """
        )
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        events = {e.strip() for e in (r["events_csv"] or "").split(",") if e.strip()}
        if event in events:
            try:
                config = json.loads(r["config_json"])
            except json.JSONDecodeError:
                continue
            out.append(
                {
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"],
                    "config": config,
                }
            )
    return out


async def _record_result(integration_id: int, status: int, body: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE integrations SET last_fired_at = ?, last_status = ? WHERE id = ?",
            (now_iso(), f"{status}: {body[:200]}", integration_id),
        )
        await db.commit()


async def _route(event: str, payload: dict[str, Any]) -> None:
    integrations = await _load_enabled_for(event)
    for itg in integrations:
        provider = PROVIDERS.get(itg["type"])
        if provider is None:
            logger.warning("unknown provider %s", itg["type"])
            continue
        try:
            status, body = await provider.dispatch(itg["config"], event, payload)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — provider isolation
            status, body = (599, f"exception: {exc}")
            logger.error("integration %s dispatch failed: %s", itg["name"], exc)
        await _record_result(itg["id"], status, body)


async def fire_test(integration_id: int) -> tuple[int, str]:
    """Fire a synthetic event so the user can verify a fresh integration."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, type, config_json FROM integrations WHERE id = ?",
            (integration_id,),
        )
        row = await cur.fetchone()
    if not row:
        return (0, "integration not found")
    provider = PROVIDERS.get(row["type"])
    if provider is None:
        return (0, f"unknown provider {row['type']}")
    try:
        config = json.loads(row["config_json"])
    except json.JSONDecodeError:
        return (0, "invalid config_json")
    status, body = await provider.dispatch(  # type: ignore[attr-defined]
        config,
        "nexus.test",
        {"message": "Test event from NEXUS integrations page"},
    )
    await _record_result(integration_id, status, body)
    return (status, body)


def register() -> None:
    """Subscribe `_route` to every event in the registry. Safe to call once
    from `app.lifespan`."""
    for event in EVENT_NAMES:
        bus.subscribe(event, _make_handler(event))


def _make_handler(event: str):
    async def _handler(payload: dict[str, Any]) -> None:
        await _route(event, payload)

    return _handler
