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
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import FlowRun, NexusFlow, Tenant
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
    "aiRouter",
    "pause",
    "webhook",
    "updateCrm",
    # 58.4+: "storyTrigger"
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
# Phase 58.4a — analytics response models
# ---------------------------------------------------------------------------


class NodeStat(BaseModel):
    node_id: str
    visits: int
    failures: int


class FlowAnalytics(BaseModel):
    runs: dict[str, Any]
    nodes: list[NodeStat]
    window_days: int


class FlowAnalyticsSummaryRow(BaseModel):
    flow_id: uuid.UUID
    total: int
    completed: int
    failed: int
    success_rate: float


class FlowAnalyticsSummary(BaseModel):
    flows: list[FlowAnalyticsSummaryRow]
    window_days: int


# ---------------------------------------------------------------------------
# Phase 61 — per-run execution history (Executions dashboard + canvas overlay)
# ---------------------------------------------------------------------------


class FlowRunRead(BaseModel):
    """One execution row for the Executions table."""

    id: uuid.UUID
    status: str
    current_node_id: str | None = None
    failed_node_id: str | None = None
    started_at: datetime
    updated_at: datetime
    run_time_ms: int


class FlowRunListResponse(BaseModel):
    runs: list[FlowRunRead]
    total: int
    limit: int
    offset: int


class FlowRunDetail(FlowRunRead):
    """Single execution incl. the visited-node trail for the canvas overlay."""

    path: list[str] = []


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


# ---------------------------------------------------------------------------
# Phase 58.4a — analytics (read-only, manager-class)
#
# Registered BEFORE the per-flow detail route so ``/flows/analytics/summary``
# is matched as a literal path and never coerced into ``{flow_id}``.
# ---------------------------------------------------------------------------


def _window_start(window_days: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=window_days)


def _success_rate(completed: int, failed: int) -> float:
    """Success over *terminal* runs only — in-flight (active/waiting) runs
    don't yet count for or against. 0.0 when nothing has terminated."""
    terminal = completed + failed
    return round(completed / terminal, 4) if terminal else 0.0


def _run_time_ms(started: datetime, updated: datetime) -> int:
    """Elapsed wall-clock for a run in milliseconds (never negative).

    For terminal runs ``updated`` is the completion/failure time (FlowRun
    sets ``onupdate=func.now()``); for in-flight runs it is the last
    transition, so the value reads as "elapsed so far".
    """
    return max(0, int((updated - started).total_seconds() * 1000))


@router.get("/{tenant_id}/facebook/flows/analytics/summary")
async def flows_analytics_summary(
    tenant_id: uuid.UUID,
    window_days: int = Query(default=7, ge=1, le=365),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FlowAnalyticsSummary:
    """Per-flow run counts + success rate for the tenant (FlowsPage badges)."""
    _check_path_matches_header(tenant, tenant_id)

    stmt = (
        select(FlowRun.flow_id, FlowRun.status, func.count())
        .where(
            FlowRun.tenant_id == tenant.id,
            FlowRun.created_at >= _window_start(window_days),
        )
        .group_by(FlowRun.flow_id, FlowRun.status)
    )
    rows = (await db.execute(stmt)).all()

    per: dict[uuid.UUID, dict[str, int]] = {}
    for flow_id_val, status_val, count in rows:
        bucket = per.setdefault(
            flow_id_val,
            {"active": 0, "waiting": 0, "completed": 0, "failed": 0},
        )
        bucket[status_val] = bucket.get(status_val, 0) + int(count)

    flows = [
        FlowAnalyticsSummaryRow(
            flow_id=flow_id_val,
            total=sum(bucket.values()),
            completed=bucket["completed"],
            failed=bucket["failed"],
            success_rate=_success_rate(bucket["completed"], bucket["failed"]),
        )
        for flow_id_val, bucket in per.items()
    ]
    return FlowAnalyticsSummary(flows=flows, window_days=window_days)


@router.get("/{tenant_id}/facebook/flows/{flow_id}/analytics")
async def flow_analytics(
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    window_days: int = Query(default=7, ge=1, le=365),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FlowAnalytics:
    """Run-status counts, success rate, and per-node visit/failure metrics
    for one flow over the trailing ``window_days`` (default 7)."""
    _check_path_matches_header(tenant, tenant_id)

    # Confirm the flow belongs to this tenant before reporting on it.
    owns = (
        await db.execute(
            select(NexusFlow.id).where(
                NexusFlow.id == flow_id,
                NexusFlow.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if owns is None:
        raise HTTPException(status_code=404, detail="flow_not_found")

    rows = (
        await db.execute(
            select(FlowRun.status, FlowRun.path, FlowRun.failed_node_id).where(
                FlowRun.flow_id == flow_id,
                FlowRun.tenant_id == tenant.id,
                FlowRun.created_at >= _window_start(window_days),
            )
        )
    ).all()

    status_counts = {"active": 0, "waiting": 0, "completed": 0, "failed": 0}
    visits: dict[str, int] = {}
    failures: dict[str, int] = {}
    for status_val, path, failed_node_id in rows:
        status_counts[status_val] = status_counts.get(status_val, 0) + 1
        for node_id in path or []:
            visits[node_id] = visits.get(node_id, 0) + 1
        if failed_node_id:
            failures[failed_node_id] = failures.get(failed_node_id, 0) + 1

    nodes = [
        NodeStat(
            node_id=node_id,
            visits=visits.get(node_id, 0),
            failures=failures.get(node_id, 0),
        )
        for node_id in sorted(set(visits) | set(failures))
    ]

    return FlowAnalytics(
        runs={
            "total": sum(status_counts.values()),
            **status_counts,
            "success_rate": _success_rate(
                status_counts["completed"], status_counts["failed"]
            ),
        },
        nodes=nodes,
        window_days=window_days,
    )


async def _assert_flow_owned(
    db: AsyncSession, flow_id: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    """404 unless ``flow_id`` belongs to ``tenant_id``."""
    owns = (
        await db.execute(
            select(NexusFlow.id).where(
                NexusFlow.id == flow_id,
                NexusFlow.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if owns is None:
        raise HTTPException(status_code=404, detail="flow_not_found")


@router.get("/{tenant_id}/facebook/flows/{flow_id}/runs")
async def list_flow_runs(
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FlowRunListResponse:
    """Paginated execution history for one flow (Executions dashboard).

    Newest first. Optional ``status`` filter (active|waiting|completed|failed).
    """
    _check_path_matches_header(tenant, tenant_id)
    await _assert_flow_owned(db, flow_id, tenant.id)

    filters = [FlowRun.flow_id == flow_id, FlowRun.tenant_id == tenant.id]
    if status in ("active", "waiting", "completed", "failed"):
        filters.append(FlowRun.status == status)

    total = (
        await db.execute(select(func.count()).select_from(FlowRun).where(*filters))
    ).scalar_one_or_none() or 0

    rows = (
        await db.execute(
            select(
                FlowRun.id,
                FlowRun.status,
                FlowRun.current_node_id,
                FlowRun.failed_node_id,
                FlowRun.created_at,
                FlowRun.updated_at,
            )
            .where(*filters)
            .order_by(FlowRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    # Index access works for both real SQLAlchemy Row objects and the test
    # double's plain tuples.
    runs = [
        FlowRunRead(
            id=r[0],
            status=r[1],
            current_node_id=r[2],
            failed_node_id=r[3],
            started_at=r[4],
            updated_at=r[5],
            run_time_ms=_run_time_ms(r[4], r[5]),
        )
        for r in rows
    ]
    return FlowRunListResponse(
        runs=runs, total=int(total), limit=limit, offset=offset
    )


@router.get("/{tenant_id}/facebook/flows/{flow_id}/runs/{run_id}")
async def get_flow_run(
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    run_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> FlowRunDetail:
    """Single execution incl. the visited-node ``path`` and ``failed_node_id``
    for the read-only canvas overlay."""
    _check_path_matches_header(tenant, tenant_id)

    row = (
        await db.execute(
            select(FlowRun).where(
                FlowRun.id == run_id,
                FlowRun.flow_id == flow_id,
                FlowRun.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="run_not_found")

    return FlowRunDetail(
        id=row.id,
        status=row.status,
        current_node_id=row.current_node_id,
        failed_node_id=row.failed_node_id,
        started_at=row.created_at,
        updated_at=row.updated_at,
        run_time_ms=_run_time_ms(row.created_at, row.updated_at),
        path=list(row.path or []),
    )
