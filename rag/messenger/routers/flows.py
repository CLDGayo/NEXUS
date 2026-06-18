"""Phase 58.1 — CRUD REST API for nexus_flows table.

Tenant-gated routes (require_manager — owner+admin):
    GET    /api/tenants/{tenant_id}/facebook/flows
    POST   /api/tenants/{tenant_id}/facebook/flows
    PUT    /api/tenants/{tenant_id}/facebook/flows/{flow_id}
    DELETE /api/tenants/{tenant_id}/facebook/flows/{flow_id}

Tenant resolution is header-based (X-Tenant-ID via require_manager →
get_current_tenant). The path ``{tenant_id}`` is a guard reconciled with the
resolved tenant; a mismatch yields 400.

``FlowStateModel`` mirrors the React Flow JSON round-trip exactly so the
canvas saves/loads without any transformation layer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import NexusFlow, Tenant
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["NEXUS Flows"])

# ---------------------------------------------------------------------------
# Node / Edge / Canvas Pydantic models (mirror React Flow JSON)
# ---------------------------------------------------------------------------

NodeType = Literal[
    "commentTrigger",
    "dmTrigger",
    "condition",
    "sendMessage",
    "waitForInput",
    # 58.2+: "aiRouter", "pause", "updateCrm", "webhook", "storyTrigger"
]

_TRIGGER_TYPES: frozenset[str] = frozenset(
    {"commentTrigger", "dmTrigger", "storyTrigger"}
)


class FlowNode(BaseModel):
    id: str
    type: NodeType
    position: dict[str, float]
    data: dict[str, Any] = {}


class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None


class FlowStateModel(BaseModel):
    # NOTE: no exactly-one-trigger validator here. An *inactive* draft may be
    # saved empty/partial so the canvas can persist work-in-progress. The
    # trigger rule is enforced at the router level only when is_active=True
    # (see _require_one_trigger_if_active).
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    viewport: dict[str, float] | None = None


# ---------------------------------------------------------------------------
# NexusFlow CRUD Pydantic schemas
# ---------------------------------------------------------------------------


class NexusFlowCreate(BaseModel):
    page_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    flow_state: FlowStateModel = Field(default_factory=lambda: FlowStateModel(nodes=[], edges=[]))  # type: ignore[call-arg]
    is_active: bool = False


class NexusFlowUpdate(BaseModel):
    page_id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    flow_state: FlowStateModel | None = None
    is_active: bool | None = None


class NexusFlowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    page_id: str
    name: str
    flow_state: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


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


def _trigger_count(flow_state: dict[str, Any]) -> int:
    nodes = flow_state.get("nodes") or []
    return sum(
        1 for n in nodes if isinstance(n, dict) and n.get("type") in _TRIGGER_TYPES
    )


def _require_one_trigger_if_active(flow_state: dict[str, Any], is_active: bool) -> None:
    """An *active* flow must have exactly one trigger node.

    Inactive drafts may be saved empty/partial (work-in-progress canvas), so the
    rule is only enforced when the flow is being activated / saved active.
    """
    if is_active and _trigger_count(flow_state) != 1:
        raise HTTPException(
            status_code=422,
            detail="active_flow_requires_exactly_one_trigger",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/facebook/flows")
async def list_flows(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[NexusFlowRead]:
    _check_path_matches_header(tenant, tenant_id)

    stmt = (
        select(NexusFlow)
        .where(NexusFlow.tenant_id == tenant.id)
        .order_by(NexusFlow.created_at)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [NexusFlowRead.model_validate(row) for row in rows]


@router.post("/{tenant_id}/facebook/flows", status_code=201)
async def create_flow(
    tenant_id: uuid.UUID,
    body: NexusFlowCreate,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> NexusFlowRead:
    _check_path_matches_header(tenant, tenant_id)

    data = body.model_dump()
    # Serialise FlowStateModel → plain dict for the JSONB column.
    if isinstance(data.get("flow_state"), dict):
        flow_state_dict = data["flow_state"]
    else:
        flow_state_dict = body.flow_state.model_dump()
    data["flow_state"] = flow_state_dict

    _require_one_trigger_if_active(flow_state_dict, body.is_active)

    row = NexusFlow(tenant_id=tenant.id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    _log.info(
        "flows.create: tenant=%s page_id=%s name=%r",
        tenant.id,
        row.page_id,
        row.name,
    )
    return NexusFlowRead.model_validate(row)


@router.put("/{tenant_id}/facebook/flows/{flow_id}")
async def update_flow(
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    body: NexusFlowUpdate,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> NexusFlowRead:
    _check_path_matches_header(tenant, tenant_id)

    stmt = select(NexusFlow).where(
        NexusFlow.id == flow_id,
        NexusFlow.tenant_id == tenant.id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="flow_not_found")

    updates = body.model_dump(exclude_unset=True)
    if "flow_state" in updates and updates["flow_state"] is not None:
        # FlowStateModel already validated; serialise to dict for JSONB.
        fs = updates["flow_state"]
        if hasattr(fs, "model_dump"):
            updates["flow_state"] = fs.model_dump()

    # Enforce the trigger rule against the *effective* post-update state:
    # the new is_active if set (else the row's current value) and the new
    # flow_state if set (else the row's current value). Activating a flow whose
    # canvas lacks exactly one trigger — or editing an already-active flow into
    # an invalid shape — is rejected.
    effective_active = updates.get("is_active", row.is_active)
    effective_flow_state = (
        updates["flow_state"]
        if "flow_state" in updates and updates["flow_state"] is not None
        else (row.flow_state or {})
    )
    _require_one_trigger_if_active(effective_flow_state, effective_active)

    for field, value in updates.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)

    _log.info(
        "flows.update: tenant=%s flow_id=%s",
        tenant.id,
        flow_id,
    )
    return NexusFlowRead.model_validate(row)


@router.delete(
    "/{tenant_id}/facebook/flows/{flow_id}",
    status_code=204,
    response_class=Response,
)
async def delete_flow(
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    _check_path_matches_header(tenant, tenant_id)

    stmt = select(NexusFlow).where(
        NexusFlow.id == flow_id,
        NexusFlow.tenant_id == tenant.id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="flow_not_found")

    await db.delete(row)
    await db.commit()

    _log.info(
        "flows.delete: tenant=%s flow_id=%s",
        tenant.id,
        flow_id,
    )
    return Response(status_code=204)
