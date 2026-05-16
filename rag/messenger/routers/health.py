"""Liveness probes — independent of upstream service health.

Both ``/health`` and ``/api/health`` are mounted so the docker-compose
healthcheck (which targets ``/api/health``) keeps working alongside the
preferred semantic path.
"""

from __future__ import annotations

from fastapi import APIRouter

from rag.messenger.schemas import HealthResponse

router = APIRouter(tags=["health"])

_PAYLOAD = HealthResponse(status="ok", service="nexus-messenger", version="0.2.0")


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return _PAYLOAD


@router.get(
    "/api/health",
    response_model=HealthResponse,
    include_in_schema=False,
)
async def api_health() -> HealthResponse:
    return _PAYLOAD
