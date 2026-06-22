"""Phase 65 — Audience CRM router.

Read + light-edit surface over ``app.flow_contacts`` (the durable per-sender
CRM record written by the flow engine's ``updateCrm`` / ``userInput`` nodes).
Manager-class, tenant-scoped end to end: every query filters by
``FlowContact.tenant_id == tenant.id`` so one workspace can never read or edit
another workspace's audience.

``attributes`` (JSONB dict) is the dynamic **custom-fields** store — there is
no fixed schema, so PATCH *merges* keys (a ``null`` value deletes that key)
rather than replacing the whole object.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import FlowContact, Tenant
from routers.deps import require_manager

router = APIRouter(tags=["audience"])


def _serialize(c: FlowContact) -> dict[str, Any]:
    attrs = dict(c.attributes or {})
    # Name / avatar are not first-class columns; surface them from attributes
    # when a flow captured them, else the UI falls back to the sender id.
    name = attrs.get("name") or attrs.get("_name")
    avatar = attrs.get("profile_picture_url") or attrs.get("_avatar")
    return {
        "id": str(c.id),
        "sender_id": c.sender_id,
        "page_id": c.page_id,
        "name": name,
        "profile_picture_url": avatar,
        "tags": list(c.tags or []),
        "custom_fields": attrs,
        "hot_lead": bool(c.hot_lead),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_interaction_at": c.updated_at.isoformat() if c.updated_at else None,
    }


class AudiencePatch(BaseModel):
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    hot_lead: bool | None = None


@router.get("")
async def list_audience(
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=128),
    hot_lead: bool | None = Query(default=None),
) -> dict[str, Any]:
    """Paginated audience for the active workspace, newest interaction first."""
    filters = [FlowContact.tenant_id == tenant.id]
    if hot_lead is not None:
        filters.append(FlowContact.hot_lead == hot_lead)
    if q:
        filters.append(FlowContact.sender_id.ilike(f"%{q.strip()}%"))

    total = (
        await db.execute(select(func.count()).select_from(FlowContact).where(*filters))
    ).scalar_one_or_none() or 0

    rows = (
        (
            await db.execute(
                select(FlowContact)
                .where(*filters)
                .order_by(FlowContact.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "contacts": [_serialize(r) for r in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.patch("/{contact_id}")
async def update_audience(
    contact_id: uuid.UUID,
    body: AudiencePatch,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Edit a single contact's tags / custom fields / hot-lead flag."""
    contact = (
        await db.execute(
            select(FlowContact).where(
                FlowContact.id == contact_id,
                FlowContact.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="contact_not_found")

    changed = False
    if body.tags is not None:
        # Reassign (don't mutate) so SQLAlchemy flags the JSONB column dirty.
        contact.tags = sorted({str(t) for t in body.tags if str(t).strip()})
        changed = True
    if body.custom_fields is not None:
        merged = dict(contact.attributes or {})
        for key, value in body.custom_fields.items():
            if value is None:
                merged.pop(key, None)  # null deletes the field
            else:
                merged[key] = value
        contact.attributes = merged
        changed = True
    if body.hot_lead is not None:
        contact.hot_lead = body.hot_lead
        changed = True
    if not changed:
        raise HTTPException(status_code=422, detail="no_fields_to_update")

    contact.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(contact)
    return _serialize(contact)
