"""Liveness + readiness probes for the messenger surface.

* ``/health`` and ``/api/health`` — cheap, dependency-free liveness. The
  docker-compose healthcheck targets ``/api/health``; the public LB only
  ever sees ``/health`` so a broken upstream does not flap container
  restarts.
* ``/health/ready`` — fans out to Qdrant, Postgres, Redis and LiteLLM in
  parallel with short per-probe timeouts. Returns 200 only when every
  upstream answers. Phase 8 nginx-level checks point at this so a
  half-broken stack stops being routed real traffic.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import asyncpg
import httpx
from fastapi import APIRouter, Response, status

from rag.config import settings
from rag.messenger.redis_client import get_redis
from rag.messenger.schemas import HealthResponse

_log = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_PAYLOAD = HealthResponse(status="ok", service="nexus-messenger", version="0.2.0")
_PROBE_TIMEOUT_S = 3.0


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


# ---------------------------------------------------------------------------
# Readiness — aggregates Qdrant / Postgres / Redis / LiteLLM
# ---------------------------------------------------------------------------

ProbeStatus = Literal["ok", "fail"]


async def _probe_qdrant() -> ProbeStatus:
    headers = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz", headers=headers)
        return "ok" if resp.status_code == 200 else "fail"


async def _probe_postgres() -> ProbeStatus:
    # Strip SQLAlchemy driver prefix so asyncpg consumes a libpq-style DSN.
    dsn = settings.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=_PROBE_TIMEOUT_S)
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()
    return "ok"


async def _probe_redis() -> ProbeStatus:
    client = get_redis()
    pong = await asyncio.wait_for(client.ping(), timeout=_PROBE_TIMEOUT_S)
    return "ok" if pong else "fail"


async def _probe_litellm() -> ProbeStatus:
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        resp = await client.get(f"{settings.litellm_base_url.rstrip('/')}/health/liveliness")
        return "ok" if resp.status_code == 200 else "fail"


ProbeFn = Callable[[], Awaitable[ProbeStatus]]

_PROBES: dict[str, ProbeFn] = {
    "qdrant": _probe_qdrant,
    "postgres": _probe_postgres,
    "redis": _probe_redis,
    "litellm": _probe_litellm,
}


@router.get(
    "/health/ready",
    summary="Aggregated readiness probe — 200 only when every upstream is reachable.",
)
async def readiness(response: Response) -> dict[str, str]:
    results = await asyncio.gather(
        *(_run_probe(name, fn) for name, fn in _PROBES.items()),
        return_exceptions=False,
    )
    report = dict(results)
    if any(v != "ok" for v in report.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


async def _run_probe(name: str, fn: ProbeFn) -> tuple[str, ProbeStatus]:
    try:
        return name, await fn()
    except Exception as exc:
        _log.warning("readiness probe %s failed: %s", name, exc)
        return name, "fail"
