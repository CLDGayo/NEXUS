"""Phase 66 — Audience Broadcasting REST API.

Manager-gated routes (``require_manager`` — owner+admin), tenant-scoped and
header/path reconciled exactly like the Phase 58 flows router:

    POST /api/tenants/{tenant_id}/facebook/broadcasts/reach
    POST /api/tenants/{tenant_id}/facebook/broadcasts/fire

A "broadcast" starts an existing NEXUS Flow for every contact matching a target
filter (``tag`` and/or ``hot_lead``). ``/reach`` is a dry-run that returns the
*Calculated Reach* (how many matched contacts are inside Meta's messaging
window) so the operator can preview before sending; ``/fire`` enqueues one
``fb_broadcast`` job per eligible contact and returns the queued/skipped counts.

Meta 24-hour compliance (the headline guardrail)
-------------------------------------------------
Meta's *standard messaging window* permits messaging a user only within 24 hours
of their last inbound **Messenger message** to the page. We enforce this with a
single source of truth — the pure predicate :func:`_within_messaging_window` —
applied to ``flow_contacts.last_interaction_at`` (stamped per inbound DM by
``touch_contact_interaction``). Contacts whose last interaction is older than the
window, or who have never messaged the page (``NULL``), are **skipped and
logged** so the tenant's page rating is never put at risk by an out-of-window
send. The same predicate drives both ``/reach`` and ``/fire``, so the preview can
never disagree with what actually fires.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import FlowContact, NexusFlow, Tenant
from rag.messenger.flow_engine import enqueue_broadcast_job
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Broadcasts"])

# Meta standard messaging window. Centralised so the predicate, the response
# payloads, and the UI copy all reference one number.
MESSAGING_WINDOW_HOURS = 24

# How many skipped sender ids to enumerate in the structured fire log before
# truncating (the aggregate count is always logged in full).
_SKIPPED_LOG_CAP = 50


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BroadcastFilters(BaseModel):
    """Audience selection criteria. Both are ANDed; omitted fields don't filter.

    - ``tag``: include only contacts whose ``tags`` JSONB array contains it.
    - ``hot_lead``: when ``True``, include only contacts flagged ``hot_lead``.
      ``False``/``None`` applies no hot-lead constraint.
    """

    tag: str | None = Field(default=None, max_length=128)
    hot_lead: bool | None = None


class BroadcastRequest(BaseModel):
    flow_id: uuid.UUID
    filters: BroadcastFilters = Field(default_factory=BroadcastFilters)


class ReachResponse(BaseModel):
    flow_id: uuid.UUID
    total_matched: int
    eligible: int
    skipped_outside_window: int
    window_hours: int = MESSAGING_WINDOW_HOURS


class FireResponse(BaseModel):
    flow_id: uuid.UUID
    total_matched: int
    queued: int
    skipped_outside_window: int
    window_hours: int = MESSAGING_WINDOW_HOURS


# ---------------------------------------------------------------------------
# Compliance core — single source of truth for the 24h window
# ---------------------------------------------------------------------------


def _within_messaging_window(
    last_interaction_at: datetime | None,
    now: datetime,
    hours: int = MESSAGING_WINDOW_HOURS,
) -> bool:
    """Return True iff ``last_interaction_at`` is inside Meta's messaging window.

    ``None`` (the sender has never messaged the page) is **never** eligible — the
    conservative, compliant default. Naive timestamps are treated as UTC
    defensively, though the column is ``TIMESTAMPTZ`` and always returns
    tz-aware values from Postgres.
    """
    if last_interaction_at is None:
        return False
    if last_interaction_at.tzinfo is None:
        last_interaction_at = last_interaction_at.replace(tzinfo=timezone.utc)
    return last_interaction_at >= now - timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Guards / query helpers
# ---------------------------------------------------------------------------


def _check_path_matches_header(tenant: Tenant, tenant_id: uuid.UUID) -> None:
    """Reject requests whose path id disagrees with ``X-Tenant-ID``."""
    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )


def _matched_contacts_stmt(
    tenant_id: uuid.UUID, page_id: str, filters: BroadcastFilters
):
    """Build the audience query: (tenant, page) scoped + tag/hot_lead filters.

    Selects only the two columns the window split needs, keeping the audience
    scan lean even for large contact lists.
    """
    stmt = select(FlowContact.sender_id, FlowContact.last_interaction_at).where(
        FlowContact.tenant_id == tenant_id,
        FlowContact.page_id == page_id,
    )
    if filters.tag:
        # JSONB ``@>`` containment: tags array includes the requested label.
        stmt = stmt.where(FlowContact.tags.contains([filters.tag]))
    if filters.hot_lead:
        stmt = stmt.where(FlowContact.hot_lead.is_(True))
    return stmt


async def _load_flow_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, flow_id: uuid.UUID
) -> NexusFlow:
    flow = (
        await db.execute(
            select(NexusFlow).where(
                NexusFlow.id == flow_id,
                NexusFlow.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="flow_not_found")
    return flow


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/{tenant_id}/facebook/broadcasts/reach")
async def calculate_reach(
    tenant_id: uuid.UUID,
    body: BroadcastRequest,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> ReachResponse:
    """Dry-run: how many matched contacts are inside the 24h window. No send."""
    _check_path_matches_header(tenant, tenant_id)
    flow = await _load_flow_or_404(db, tenant.id, body.flow_id)

    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(_matched_contacts_stmt(tenant.id, flow.page_id, body.filters))
    ).all()

    total = len(rows)
    eligible = sum(1 for _, lia in rows if _within_messaging_window(lia, now))

    return ReachResponse(
        flow_id=flow.id,
        total_matched=total,
        eligible=eligible,
        skipped_outside_window=total - eligible,
    )


@router.post("/{tenant_id}/facebook/broadcasts/fire")
async def fire_broadcast(
    tenant_id: uuid.UUID,
    body: BroadcastRequest,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FireResponse:
    """Enqueue the target flow for every eligible (in-window) matched contact.

    Out-of-window contacts are skipped and logged (count always; sender ids up
    to ``_SKIPPED_LOG_CAP``) so an out-of-window send can never silently harm
    the tenant's page rating.
    """
    _check_path_matches_header(tenant, tenant_id)
    flow = await _load_flow_or_404(db, tenant.id, body.flow_id)

    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(_matched_contacts_stmt(tenant.id, flow.page_id, body.filters))
    ).all()
    total = len(rows)

    eligible: list[str] = []
    skipped: list[str] = []
    for sender_id, lia in rows:
        if _within_messaging_window(lia, now):
            eligible.append(sender_id)
        else:
            skipped.append(sender_id)

    if skipped:
        _log.info(
            "broadcast.skipped_outside_window tenant=%s flow=%s page=%s "
            "count=%d senders=%s",
            tenant.id,
            flow.id,
            flow.page_id,
            len(skipped),
            ",".join(skipped[:_SKIPPED_LOG_CAP])
            + ("…" if len(skipped) > _SKIPPED_LOG_CAP else ""),
        )

    for sender_id in eligible:
        await enqueue_broadcast_job(
            page_id=flow.page_id,
            flow_id=str(flow.id),
            sender_id=sender_id,
            tenant_id=str(tenant.id),
        )

    _log.info(
        "broadcast.fire tenant=%s flow=%s page=%s matched=%d queued=%d skipped=%d",
        tenant.id,
        flow.id,
        flow.page_id,
        total,
        len(eligible),
        len(skipped),
    )

    return FireResponse(
        flow_id=flow.id,
        total_matched=total,
        queued=len(eligible),
        skipped_outside_window=len(skipped),
    )
