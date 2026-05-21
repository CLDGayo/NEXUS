"""Nexus unified FastAPI entrypoint (Phase 9 cutover).

Absorbs the v1 SPA / admin / chat surface (formerly ``rag/app.py``) and the
v2 messenger webhook + LangGraph cortex into a single ASGI app served by
the Docker container. The container ``CMD`` targets ``rag.main:app``.

Routing summary:
    /                     -> SPA index.html (catch-all for client routes)
    /static/*             -> SPA assets
    /widget               -> embeddable widget
    /health, /api/health,
    /health/ready         -> v2 liveness + aggregated readiness
    /webhook/*            -> v2 messenger inbound + opt-out
    /api/auth/*           -> v1 JWT auth
    /api/chat/*           -> v1 chat SPA endpoints (stream routed through
                             the v2 LangGraph orchestrator — see chat.py)
    /api/dashboard/*      -> v1 KPIs
    /api/documents,
    /api/uploads,
    /api/conversations,
    /api/logs             -> v1 admin
    /api/settings/*       -> v1 settings + password rotation
    /api/changelog/*      -> v1 changelog
    /api/integrations/*   -> v1 webhook integrations
    /api/tokens/*         -> v1 scoped API tokens
    /api/resources/*      -> v1 prompt library

Lifespan order:
    1. ``init_db`` — v1 SQLite tables (conversations, settings, integrations,
       tokens).
    2. ``integrations_dispatcher.register`` — v1 event bus subscribers.
    3. (optional) ``AsyncPostgresSaver.setup`` — LangGraph checkpoint schema
       when ``LANGGRAPH_CHECKPOINT=postgres``. The async context is held
       for the lifetime of the app via ``AsyncExitStack``.

v1 modules use flat imports (``from database import …``). They resolve at
runtime because the Dockerfile sets ``PYTHONPATH=/app/rag`` and copies the
package into ``/app/rag``. v2 modules use absolute ``rag.…`` imports.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# v2 imports (absolute) — must come before flat v1 imports so settings load
# fails fast on missing env vars before SQLite touches disk.
from rag.config import settings  # noqa: E402
from rag.messenger.routers import health as v2_health  # noqa: E402
from rag.messenger.routers import webhook as v2_webhook  # noqa: E402
from rag.observability.tracing import init_tracing  # noqa: E402

# v1 imports (flat — resolved via PYTHONPATH=/app/rag).
from database import init_db  # noqa: E402
from integrations import dispatcher as integrations_dispatcher  # noqa: E402
from routers import (  # noqa: E402
    api_tokens,
    auth,
    changelog,
    chat,
    chat_uploads,
    conversations,
    dashboard,
    documents,
    integrations,
    logs,
    resources,
    settings as v1_settings,
    uploads,
)

_log = logging.getLogger(__name__)

# Phase 11: React SPA at nexus-ui/dist replaces the legacy rag/static/ vanilla
# app. The Vite build emits `index.html` + `assets/*.js,*.css`. The Dockerfile
# stage `ui` runs `npm run build` and copies dist into /app/nexus-ui/dist;
# locally, `npm run build` populates the same path relative to the repo.
WEBAPP_DIR = Path(__file__).parent.parent / "nexus-ui" / "dist"
WIDGET_STATIC_DIR = Path(__file__).parent / "widget-static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot v1 state, then optionally bring up the LangGraph Postgres saver."""

    await init_db()
    integrations_dispatcher.register()

    # Phase 21 — background-task registry. The Messenger webhook scheduler
    # registers each ``_handle_messenger_event`` task here so we can drain
    # them on shutdown before the AsyncExitStack closes the Postgres pool.
    background_tasks: set[asyncio.Task[Any]] = set()
    app.state.background_tasks = background_tasks
    v2_webhook.register_task_tracker(background_tasks)

    async with AsyncExitStack() as stack:
        backend = settings.langgraph_checkpoint.lower()
        if backend == "postgres":
            # psycopg3 expects a libpq DSN, not SQLAlchemy's ``+asyncpg``
            # form — strip the driver prefix on the way in.
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            dsn = settings.postgres_dsn.replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
            # Deferred import: graph.py transitively pulls retrieval.dense
            # (fastembed), which is only present in the ingest-heavy image.
            # Tests that exercise unrelated routes never hit this branch.
            from rag.orchestrator.graph import set_checkpointer

            saver_cm = AsyncPostgresSaver.from_conn_string(dsn)
            saver = await stack.enter_async_context(saver_cm)
            await saver.setup()
            set_checkpointer(saver)
            _log.info("LangGraph checkpointer: postgres (setup complete)")
        else:
            _log.info("LangGraph checkpointer: memory (dev/test default)")

        try:
            yield
        finally:
            # Drain in-flight tasks BEFORE the AsyncExitStack closes the
            # Postgres saver context — otherwise the pool can be yanked
            # mid-checkpoint and a task that was about to persist state
            # raises an InterfaceError into a finished request.
            v2_webhook.register_task_tracker(None)
            pending = list(background_tasks)
            if pending:
                drain_timeout = settings.messenger_shutdown_drain_seconds
                _log.info(
                    "lifespan.drain.waiting count=%d timeout_s=%.1f",
                    len(pending),
                    drain_timeout,
                )
                done, still_pending = await asyncio.wait(
                    pending, timeout=drain_timeout
                )
                if still_pending:
                    _log.warning(
                        "lifespan.drain.timeout cancelled=%d completed=%d",
                        len(still_pending),
                        len(done),
                    )
                    for task in still_pending:
                        task.cancel()
                else:
                    _log.info("lifespan.drain.complete count=%d", len(done))


app = FastAPI(
    title="NEXUS — Unified API",
    version="0.9.0",
    description="v1 SPA + admin + v2 Messenger webhook + LangGraph cortex.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OTEL + Langfuse bootstrap (no-op when keys absent).
init_tracing(app, service_name="nexus-api")

# v2 routers — health (/, /api/health, /health/ready) + webhook.
app.include_router(v2_health.router)
app.include_router(v2_webhook.router, prefix="/webhook")

# v1 routers — admin + SPA chat surface. ``routers.health`` is intentionally
# dropped: v2's health router already serves /health + /api/health.
app.include_router(auth.router,          prefix="/api/auth")
app.include_router(chat.router,          prefix="/api/chat")
app.include_router(chat_uploads.router,  prefix="/api/chat")
app.include_router(dashboard.router,     prefix="/api/dashboard")
app.include_router(documents.router,     prefix="/api")
app.include_router(uploads.router,       prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(logs.router,          prefix="/api")
app.include_router(v1_settings.router,   prefix="/api/settings")
app.include_router(changelog.router,     prefix="/api/changelog")
app.include_router(integrations.router,  prefix="/api/integrations")
app.include_router(api_tokens.router,    prefix="/api/tokens")
app.include_router(resources.router,     prefix="/api/resources")

# React SPA assets + widget mounts. The catch-all must be registered last so
# that named API/asset routes win the match. Vite emits hashed bundles under
# /assets/, so we serve that directory directly; the catch-all hands every
# other path the React index.html (React Router takes over client-side).
app.mount(
    "/assets",
    StaticFiles(directory=str(WEBAPP_DIR / "assets")),
    name="assets",
)
app.mount(
    "/widget-static",
    StaticFiles(directory=str(WIDGET_STATIC_DIR)),
    name="widget-static",
)


@app.get("/widget", include_in_schema=False)
async def widget() -> FileResponse:
    return FileResponse(str(WIDGET_STATIC_DIR / "widget.html"))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(WEBAPP_DIR / "index.html"))


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str) -> FileResponse:
    # Root-level static files (favicon, robots.txt, etc.) are served from
    # disk when present; everything else falls through to the React index so
    # client-side routes (/documents, /integrations, /conversations) survive
    # a hard refresh.
    if full_path:
        candidate = (WEBAPP_DIR / full_path).resolve()
        webapp_root = WEBAPP_DIR.resolve()
        # Guard against `..` path traversal escaping the build directory.
        if webapp_root in candidate.parents and candidate.is_file():
            return FileResponse(str(candidate))
    return FileResponse(str(WEBAPP_DIR / "index.html"))
