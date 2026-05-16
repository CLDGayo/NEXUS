"""Nexus v2 — Messenger webhook entry point.

Phase 2 surface adapter. Boots a minimal FastAPI app, mounts the webhook +
health routers, and bootstraps OTEL/Langfuse tracing. The container CMD
(see ``Dockerfile``) targets ``rag.messenger.main:app``.

LangGraph orchestration lands in Phase 6; this entry point currently
returns a mock acknowledgment.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from rag.config import settings
from rag.messenger.routers import health, webhook
from rag.observability.tracing import init_tracing


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Phase 9 will start the LangGraph PostgresSaver + Qdrant warmup here.
    yield


app = FastAPI(
    title="Nexus v2 Messenger",
    version="0.2.0",
    description="Phase 2 webhook surface — validates inbound, returns mock reply.",
    lifespan=lifespan,
)

# Import-time eager read so missing env fails fast at container start.
_ = settings

init_tracing(app, service_name="nexus-messenger")

app.include_router(health.router)
app.include_router(webhook.router, prefix="/webhook")
