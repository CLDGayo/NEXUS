"""Phase 57.1 — CRUD REST API for facebook_automations table.

Tenant-gated routes (require_manager — owner+admin):
    GET    /api/tenants/{tenant_id}/facebook/automations
    POST   /api/tenants/{tenant_id}/facebook/automations
    PUT    /api/tenants/{tenant_id}/facebook/automations/{automation_id}
    DELETE /api/tenants/{tenant_id}/facebook/automations/{automation_id}

Tenant resolution is header-based (X-Tenant-ID via require_manager →
get_current_tenant). The path ``{tenant_id}`` is a guard reconciled with the
resolved tenant; a mismatch yields 400.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import FacebookAutomation, Tenant
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Facebook Automations"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

MatchType = Literal["exact", "contains"]


class FacebookAutomationCreate(BaseModel):
    page_id: str = Field(..., min_length=1, max_length=64)
    trigger_keyword: str = Field(..., min_length=1, max_length=255)
    match_type: MatchType = "exact"
    reply_payload: dict[str, Any]
    is_active: bool = True

    @field_validator("reply_payload")
    @classmethod
    def _require_message_key(cls, v: dict[str, Any]) -> dict[str, Any]:
        """The worker does reply_payload['message'] — reject bad rows at the edge."""
        msg = v.get("message")
        if not isinstance(msg, str) or not msg.strip():
            raise ValueError(
                "reply_payload must contain a non-empty string 'message' key"
            )
        return v


class FacebookAutomationUpdate(BaseModel):
    page_id: str | None = Field(default=None, min_length=1, max_length=64)
    trigger_keyword: str | None = Field(default=None, min_length=1, max_length=255)
    match_type: MatchType | None = None
    reply_payload: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("reply_payload")
    @classmethod
    def _require_message_key_when_set(
        cls, v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Validate message key only when reply_payload is provided."""
        if v is None:
            return v
        msg = v.get("message")
        if not isinstance(msg, str) or not msg.strip():
            raise ValueError(
                "reply_payload must contain a non-empty string 'message' key"
            )
        return v


class FacebookAutomationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    page_id: str
    trigger_keyword: str
    match_type: str
    reply_payload: dict[str, Any]
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Path/header guard helper
# ---------------------------------------------------------------------------


def _check_path_matches_header(tenant: Tenant, tenant_id: uuid.UUID) -> None:
    """Reject requests whose path id disagrees with ``X-Tenant-ID``."""
    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/facebook/automations")
async def list_automations(
    tenant_id: uuid.UUID,
    page_id: str | None = Query(default=None),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[FacebookAutomationRead]:
    _check_path_matches_header(tenant, tenant_id)

    stmt = (
        select(FacebookAutomation)
        .where(FacebookAutomation.tenant_id == tenant.id)
        .order_by(FacebookAutomation.created_at)
    )
    if page_id is not None:
        stmt = stmt.where(FacebookAutomation.page_id == page_id)

    rows = (await db.execute(stmt)).scalars().all()
    return [FacebookAutomationRead.model_validate(row) for row in rows]


@router.post("/{tenant_id}/facebook/automations", status_code=201)
async def create_automation(
    tenant_id: uuid.UUID,
    body: FacebookAutomationCreate,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FacebookAutomationRead:
    _check_path_matches_header(tenant, tenant_id)

    row = FacebookAutomation(tenant_id=tenant.id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)

    _log.info(
        "automations.create: tenant=%s page_id=%s keyword=%r",
        tenant.id,
        row.page_id,
        row.trigger_keyword,
    )
    return FacebookAutomationRead.model_validate(row)


@router.put("/{tenant_id}/facebook/automations/{automation_id}")
async def update_automation(
    tenant_id: uuid.UUID,
    automation_id: uuid.UUID,
    body: FacebookAutomationUpdate,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FacebookAutomationRead:
    _check_path_matches_header(tenant, tenant_id)

    stmt = select(FacebookAutomation).where(
        FacebookAutomation.id == automation_id,
        FacebookAutomation.tenant_id == tenant.id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="automation_not_found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)

    _log.info(
        "automations.update: tenant=%s automation_id=%s",
        tenant.id,
        automation_id,
    )
    return FacebookAutomationRead.model_validate(row)


@router.delete(
    "/{tenant_id}/facebook/automations/{automation_id}",
    status_code=204,
    response_class=Response,
)
async def delete_automation(
    tenant_id: uuid.UUID,
    automation_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    _check_path_matches_header(tenant, tenant_id)

    stmt = select(FacebookAutomation).where(
        FacebookAutomation.id == automation_id,
        FacebookAutomation.tenant_id == tenant.id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="automation_not_found")

    await db.delete(row)
    await db.commit()

    _log.info(
        "automations.delete: tenant=%s automation_id=%s",
        tenant.id,
        automation_id,
    )
    return Response(status_code=204)
