"""Integrations router — CRUD + test-fire + Messenger token management.

Phase 30.1 — every row lives in ``app.integrations``. ``id`` is now a
UUID (was an autoincrement int); ``config`` is JSONB rather than a
TEXT-serialised JSON blob.

Phase 50 — gated by ``require_manager`` (owner or admin) end to end. Every select/insert/
update/delete filters by ``Integration.tenant_id == tenant.id`` so an
owner of workspace A cannot see, mutate, or fire-test an integration
configured under workspace B. The Messenger token management routes
(``/messenger`` and friends) operate on a single shared overlay today
(``messenger_overlay``) — the owner-role gate still applies so a
non-owner member cannot rotate the verify token even though the token
itself is global.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import messenger_overlay
from events import EVENT_NAMES
from integrations.dispatcher import fire_test
from integrations.providers import PROVIDERS

from rag.database.engine import get_async_session
from rag.database.models import Integration, MessengerPageTenant, Tenant
from routers.deps import require_manager

router = APIRouter(tags=["integrations"])

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


def _serialize(integration: Integration) -> dict[str, Any]:
    config = integration.config or {}
    return {
        "id": str(integration.id),
        "type": integration.type,
        "name": integration.name,
        "config": _redact(integration.type, dict(config)),
        "events": [e for e in (integration.events_csv or "").split(",") if e],
        "enabled": bool(integration.enabled),
        "created_at": (
            integration.created_at.isoformat() if integration.created_at else None
        ),
        "updated_at": (
            integration.updated_at.isoformat() if integration.updated_at else None
        ),
        "last_fired_at": (
            integration.last_fired_at.isoformat() if integration.last_fired_at else None
        ),
        "last_status": integration.last_status,
    }


async def _load_for_tenant(
    db: AsyncSession, integration_id: uuid.UUID, tenant_id: uuid.UUID
) -> Integration:
    stmt = select(Integration).where(
        Integration.id == integration_id,
        Integration.tenant_id == tenant_id,
    )
    integration = (await db.execute(stmt)).scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.get("")
async def list_integrations(
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict]:
    stmt = (
        select(Integration)
        .where(Integration.tenant_id == tenant.id)
        .order_by(Integration.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/events")
async def list_events(_: Tenant = Depends(require_manager)) -> dict:
    return {"events": list(EVENT_NAMES), "types": sorted(VALID_TYPES)}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 39 — Premium connector catalog (read-only stubs)
#
# Hunter (lead verification) and Akiro (analytics) are NOT provisioned
# integrations — they have no provider, no DB row, and no secrets. This
# endpoint returns a static catalog so the frontend can render polished
# "available / inactive" empty-state cards instead of guessing. It never
# reads the DB or env config, so a missing key can't raise here, and the
# core Messenger / LangGraph loops are entirely unaffected.
# ─────────────────────────────────────────────────────────────────────────────


class CatalogConnector(BaseModel):
    key: str
    name: str
    category: str
    description: str
    status: str = "inactive"
    configured: bool = False
    api_token: str | None = None
    tier: str = "enterprise"


_PREMIUM_CATALOG: tuple[CatalogConnector, ...] = (
    CatalogConnector(
        key="hunter",
        name="Hunter",
        category="Automated Lead Verification",
        description=(
            "Validate inbound lead emails in real time before they enter your "
            "GoHighLevel pipeline — cutting bounce rates and protecting sender "
            "reputation."
        ),
    ),
    CatalogConnector(
        key="akiro",
        name="Akiro",
        category="Advanced Analytics Processing",
        description=(
            "Stream conversation and conversion events into an analytics "
            "warehouse for cohort, funnel, and revenue-attribution reporting."
        ),
    ),
)


@router.get("/catalog")
async def get_integration_catalog(
    _: Tenant = Depends(require_manager),
) -> dict[str, list[dict[str, Any]]]:
    """Static premium-connector catalog. Read-only; no DB, no secrets."""
    return {"connectors": [c.model_dump() for c in _PREMIUM_CATALOG]}


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
async def get_messenger(
    request: Request,
    _: Tenant = Depends(require_manager),
) -> dict[str, Any]:
    return _messenger_payload(request)


@router.post("/messenger/rotate-verify-token")
async def rotate_messenger_verify_token(
    request: Request,
    _: Tenant = Depends(require_manager),
) -> dict[str, Any]:
    messenger_overlay.rotate_verify_token()
    return _messenger_payload(request)


@router.patch("/messenger")
async def patch_messenger(
    body: MessengerPatch,
    request: Request,
    _: Tenant = Depends(require_manager),
) -> dict[str, Any]:
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 32 — Messenger Page ↔ Tenant binding admin
#
# A Facebook Page ID is global (PK on app.messenger_page_tenants), so the
# binding is "this page now belongs to this workspace" — rebinding to a
# second tenant must explicitly DELETE the existing row first.
# ─────────────────────────────────────────────────────────────────────────────


class MessengerPageBindRequest(BaseModel):
    facebook_page_id: str = Field(..., min_length=1, max_length=64)


def _serialize_page(row: MessengerPageTenant) -> dict[str, Any]:
    return {
        "facebook_page_id": row.facebook_page_id,
        "tenant_id": str(row.tenant_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/messenger/pages")
async def list_messenger_pages(
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict[str, Any]]:
    """List the Facebook pages bound to the active tenant."""
    rows = (
        (
            await db.execute(
                select(MessengerPageTenant)
                .where(MessengerPageTenant.tenant_id == tenant.id)
                .order_by(MessengerPageTenant.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_page(r) for r in rows]


@router.post("/messenger/pages", status_code=201)
async def bind_messenger_page(
    body: MessengerPageBindRequest,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Bind a Facebook page id to the active tenant.

    Rebinding from another tenant is refused with 409 — operators must
    delete the existing binding first so the change is intentional.
    """
    existing = (
        await db.execute(
            select(MessengerPageTenant).where(
                MessengerPageTenant.facebook_page_id == body.facebook_page_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.tenant_id == tenant.id:
            return _serialize_page(existing)
        raise HTTPException(
            status_code=409,
            detail="page_bound_to_other_tenant",
        )
    row = MessengerPageTenant(
        facebook_page_id=body.facebook_page_id, tenant_id=tenant.id
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_page(row)


@router.delete(
    "/messenger/pages/{facebook_page_id}",
    status_code=204,
    response_class=Response,
)
async def unbind_messenger_page(
    facebook_page_id: str,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    """Unbind a page from the active tenant. 404 if it belongs to someone else."""
    row = (
        await db.execute(
            select(MessengerPageTenant).where(
                MessengerPageTenant.facebook_page_id == facebook_page_id,
                MessengerPageTenant.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="page_binding_not_found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("", status_code=201)
async def create_integration(
    body: IntegrationCreate,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    _validate_type(body.type)
    _validate_events(body.events)
    integration = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        type=body.type,
        name=body.name,
        config=body.config,
        events_csv=",".join(body.events),
        enabled=body.enabled,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return _serialize(integration)


@router.patch("/{integration_id}")
async def update_integration(
    integration_id: uuid.UUID,
    body: IntegrationPatch,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    if body.events is not None:
        _validate_events(body.events)

    integration = await _load_for_tenant(db, integration_id, tenant.id)

    changed = False
    if body.name is not None:
        integration.name = body.name
        changed = True
    if body.config is not None:
        integration.config = body.config
        changed = True
    if body.events is not None:
        integration.events_csv = ",".join(body.events)
        changed = True
    if body.enabled is not None:
        integration.enabled = body.enabled
        changed = True
    if not changed:
        raise HTTPException(status_code=422, detail="No fields to update")

    await db.commit()
    await db.refresh(integration)
    return _serialize(integration)


@router.delete("/{integration_id}", status_code=204, response_class=Response)
async def delete_integration(
    integration_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    integration = await _load_for_tenant(db, integration_id, tenant.id)
    await db.delete(integration)
    await db.commit()
    return Response(status_code=204)


@router.post("/{integration_id}/test")
async def test_integration(
    integration_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    # Confirm the integration belongs to this tenant before the dispatcher
    # fires — fire_test reads its own row by id, which would happily fire
    # a sibling-tenant webhook otherwise.
    await _load_for_tenant(db, integration_id, tenant.id)
    status, body = await fire_test(integration_id)
    return {"status": status, "body": body, "ok": 200 <= status < 300}
