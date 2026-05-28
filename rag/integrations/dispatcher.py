"""Subscribes to events; routes payloads to enabled integrations.

Phase 30.1 — backed by ``app.integrations`` through SQLAlchemy 2.0 async
sessions opened directly from the engine sessionmaker (no request scope
is available on the event bus).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from events import EVENT_NAMES, bus

from rag.database.engine import get_sessionmaker
from rag.database.models import Integration

from .providers import PROVIDERS

logger = logging.getLogger(__name__)


async def _load_enabled_for(event: str) -> list[dict[str, Any]]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        stmt = select(Integration).where(Integration.enabled.is_(True))
        rows = (await db.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        events = {
            e.strip()
            for e in (row.events_csv or "").split(",")
            if e.strip()
        }
        if event in events:
            out.append(
                {
                    "id": row.id,
                    "type": row.type,
                    "name": row.name,
                    "config": dict(row.config or {}),
                }
            )
    return out


async def _record_result(
    integration_id: uuid.UUID, status: int, body: str
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        integration = await db.get(Integration, integration_id)
        if integration is None:
            return
        integration.last_fired_at = datetime.now(timezone.utc)
        integration.last_status = f"{status}: {body[:200]}"
        await db.commit()


async def _route(event: str, payload: dict[str, Any]) -> None:
    integrations = await _load_enabled_for(event)
    for itg in integrations:
        provider = PROVIDERS.get(itg["type"])
        if provider is None:
            logger.warning("unknown provider %s", itg["type"])
            continue
        try:
            status, body = await provider.dispatch(  # type: ignore[attr-defined]
                itg["config"], event, payload
            )
        except Exception as exc:  # noqa: BLE001 — provider isolation
            status, body = (599, f"exception: {exc}")
            logger.error(
                "integration %s dispatch failed: %s", itg["name"], exc
            )
        await _record_result(itg["id"], status, body)


async def fire_test(integration_id: uuid.UUID) -> tuple[int, str]:
    """Fire a synthetic event so the user can verify a fresh integration."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        integration = await db.get(Integration, integration_id)
    if integration is None:
        return (0, "integration not found")
    provider = PROVIDERS.get(integration.type)
    if provider is None:
        return (0, f"unknown provider {integration.type}")
    status, body = await provider.dispatch(  # type: ignore[attr-defined]
        dict(integration.config or {}),
        "nexus.test",
        {"message": "Test event from NEXUS integrations page"},
    )
    await _record_result(integration.id, status, body)
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
