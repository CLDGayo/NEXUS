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
    1. ``integrations_dispatcher.register`` — event bus subscribers.
    2. (optional) ``AsyncPostgresSaver.setup`` — LangGraph checkpoint schema
       when ``LANGGRAPH_CHECKPOINT=postgres``. The async context is held
       for the lifetime of the app via ``AsyncExitStack``.

Phase 30.1 retired the SQLite bootstrap step; every legacy table now
lives in Postgres and the schema is owned exclusively by Alembic.

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
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# v2 imports (absolute) — must come before flat v1 imports so settings load
# fails fast on missing env vars before SQLite touches disk.
from rag.auth import (  # noqa: E402
    UserCreate,
    UserRead,
    UserUpdate,
    auth_backend,
    fastapi_users,
)
from rag.config import settings  # noqa: E402
from rag.database.engine import dispose_engine  # noqa: E402
from rag.messenger.routers import auth_fb as v2_fb_oauth  # noqa: E402
from rag.messenger.routers import automations as v2_fb_automations  # noqa: E402
from rag.messenger.routers import flows as v2_fb_flows  # noqa: E402
from rag.messenger.routers import health as v2_health  # noqa: E402
from rag.messenger.routers import outbound as v2_outbound  # noqa: E402
from rag.messenger.routers import webhook as v2_webhook  # noqa: E402
from rag.auth.oauth import router as v2_google_oauth  # noqa: E402
from rag.auth.session import router as v2_auth_session  # noqa: E402
from rag.observability.tracing import init_tracing  # noqa: E402
from rag.routers import admin_users as v2_admin_users  # noqa: E402
from rag.routers import domain_join as v2_domain_join  # noqa: E402
from rag.routers import profile as v2_profile  # noqa: E402
from rag.routers import v2_tenants  # noqa: E402
from rag.routers.tenant_invites import public_router as v2_invites_public  # noqa: E402
from rag.routers.tenant_invites import router as v2_invites  # noqa: E402

# v1 imports (flat — resolved via PYTHONPATH=/app/rag).
from integrations import dispatcher as integrations_dispatcher  # noqa: E402
from routers import (  # noqa: E402
    api_tokens,
    audience,
    auth,
    changelog,
    chat,
    chat_uploads,
    conversations,
    dashboard,
    docs_content,
    documents,
    integrations,
    logs,
    objects,
    products,
    resources,
    settings as v1_settings,
    uploads,
    workspace_ai_settings,
)

_log = logging.getLogger(__name__)

# Phase 11: React SPA at nexus-ui/dist replaces the legacy rag/static/ vanilla
# app. The Vite build emits `index.html` + `assets/*.js,*.css`. The Dockerfile
# stage `ui` runs `npm run build` and copies dist into /app/nexus-ui/dist;
# locally, `npm run build` populates the same path relative to the repo.
WEBAPP_DIR = Path(__file__).parent.parent / "nexus-ui" / "dist"
WIDGET_STATIC_DIR = Path(__file__).parent / "widget-static"


def _enforce_jwt_secret() -> None:
    """Phase 27 — refuse to boot without a non-trivial ``NEXUS_JWT_SECRET``.

    Bypassed under pytest (PYTEST_CURRENT_TEST set by conftest stubs)."""

    import os

    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("NEXUS_SKIP_JWT_GUARD"):
        return
    secret = settings.nexus_jwt_secret
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "NEXUS_JWT_SECRET is unset or shorter than 32 bytes — "
            "set a 32+ byte secret (e.g. `openssl rand -hex 32`) in the env "
            "before booting the API."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot v1 state, then optionally bring up the LangGraph Postgres saver."""

    _enforce_jwt_secret()
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
                done, still_pending = await asyncio.wait(pending, timeout=drain_timeout)
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

            # Phase 27 — release the asyncpg pool the fastapi-users SQLA
            # engine has been holding. Safe even when no auth route was hit
            # because the engine is lazily constructed.
            await dispose_engine()


app = FastAPI(
    title="NEXUS — Unified API",
    version="0.9.0",
    description="v1 SPA + admin + v2 Messenger webhook + LangGraph cortex.",
    lifespan=lifespan,
)

# Cross-Domain Misconfiguration (ZAP Medium, 2026-06-20): the prior
# ``allow_origins=["*"]`` exposed every API response to any origin. The SPA
# and embeddable widget both call the API same-origin (relative URLs), so we
# restrict CORS to an explicit, env-overridable allowlist (prod origins +
# local Vite dev). ``allow_credentials`` stays on so cookie/JWT auth survives
# for the allowed origins — invalid only when paired with a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Response security headers (ZAP 2026-06-20 remediation): CSP + HSTS +
# anti-sniffing/referrer hardening on every response. Registered before the
# CORS middleware in source so it sits *inside* the CORS layer and never
# clobbers ``Access-Control-*`` headers on preflight responses. Widget routes
# get a permissive ``frame-ancestors *`` CSP so the chat widget stays
# embeddable; everything else is framed only by itself.
@app.middleware("http")
async def security_headers(request: Any, call_next: Any) -> Any:
    response = await call_next(request)
    if not settings.security_headers_enabled:
        return response

    path = request.url.path
    is_widget = path == "/widget" or path.startswith("/widget-static")
    response.headers.setdefault(
        "Content-Security-Policy",
        settings.security_csp_widget if is_widget else settings.security_csp,
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    # X-Frame-Options is the legacy companion to frame-ancestors. Skip it for
    # widget routes so cross-site framing of the embed is not blocked by old
    # browsers that ignore CSP frame-ancestors.
    if not is_widget:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")

    # HSTS only over HTTPS. We honour both the resolved scheme (set by uvicorn
    # --proxy-headers) AND the raw X-Forwarded-Proto header, because behind
    # nginx the container sees the docker-bridge source IP, which is outside
    # uvicorn's default ``--forwarded-allow-ips=127.0.0.1`` trust list — so the
    # scheme can stay ``http`` even on a genuine HTTPS request. An HSTS header
    # delivered over plain HTTP is ignored by browsers, so this is safe.
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    if is_https and settings.hsts_max_age > 0:
        response.headers.setdefault(
            "Strict-Transport-Security",
            f"max-age={settings.hsts_max_age}; includeSubDomains",
        )

    # Re-examine Cache-control (ZAP Info, alert 10015): responses that may carry
    # sensitive data must not be cached by browsers or shared proxies. This
    # covers API/auth/webhook payloads AND the SPA HTML shell — the authed app
    # document itself must always be revalidated so a logged-out browser never
    # replays a stale authenticated shell from cache. Hashed, immutable static
    # assets under /assets (JS/CSS — not text/html) are left untouched so the
    # CDN can cache them. The HTML branch uses direct assignment to override the
    # weak ``Cache-Control: no-transform`` that the upstream nginx vhost emits.
    content_type = response.headers.get("content-type", "")
    is_html = content_type.startswith("text/html")
    if path.startswith("/api/") or path.startswith("/webhook"):
        response.headers.setdefault(
            "Cache-Control", "no-store, no-cache, must-revalidate"
        )
        response.headers.setdefault("Pragma", "no-cache")
    elif is_html:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"

    return response


# OTEL + Langfuse bootstrap (no-op when keys absent).
init_tracing(app, service_name="nexus-api")

# v2 routers — health (/, /api/health, /health/ready) + webhook + outbound.
app.include_router(v2_health.router)
app.include_router(v2_webhook.router, prefix="/webhook")
app.include_router(v2_outbound.router, prefix="/webhook")

# v1 routers — admin + SPA chat surface. ``routers.health`` is intentionally
# dropped: v2's health router already serves /health + /api/health.
app.include_router(auth.router, prefix="/api/auth")

# Phase 27 — fastapi-users routes coexist with the legacy admin login. The
# legacy POST /api/auth/login stays mounted (decommissioned in Part 2 once
# the SPA cuts over to /api/auth/jwt/login).
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/api/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)

# Phase 28 Part 1 — profile self-service (custom password change) + superuser
# admin provisioning. Mounted after fastapi-users' get_users_router so the
# built-in `/api/users/me` (GET + PATCH) remains routable.
app.include_router(v2_profile.router, prefix="/api/users", tags=["profile"])
app.include_router(v2_admin_users.router, prefix="/api/admin", tags=["admin"])

# Phase 29 — tenant CRUD + membership. Router declares its own /api/tenants
# prefix; mount with no extra prefix here.
app.include_router(v2_tenants.router)
# Phase 51 — invite routes (/api/tenants/{id}/invites) + public accept (/api/invites/accept).
app.include_router(v2_invites)
app.include_router(v2_invites_public)
# Phase 61 — one-click Meta OAuth page connect (/api/facebook/login, /callback).
app.include_router(v2_fb_oauth.router)
# Phase 57.1 — facebook automation CRUD (/api/tenants/{id}/facebook/automations).
app.include_router(v2_fb_automations.router)
# Phase 58.1 — NEXUS Flow CRUD (/api/tenants/{id}/facebook/flows).
app.include_router(v2_fb_flows.router)
# Phase 56 — Google SSO (routers carry their own /api/auth* prefixes).
app.include_router(v2_google_oauth)
app.include_router(v2_auth_session)
app.include_router(v2_domain_join.router)

app.include_router(chat.router, prefix="/api/chat")
app.include_router(chat_uploads.router, prefix="/api/chat")
app.include_router(dashboard.router, prefix="/api/dashboard")
app.include_router(documents.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(v1_settings.router, prefix="/api/settings")
app.include_router(changelog.router, prefix="/api/changelog")
app.include_router(integrations.router, prefix="/api/integrations")
app.include_router(audience.router, prefix="/api/audience")
app.include_router(api_tokens.router, prefix="/api/tokens")
app.include_router(workspace_ai_settings.router, prefix="/api/workspace")
app.include_router(resources.router, prefix="/api/resources")
app.include_router(products.router, prefix="/api")
app.include_router(objects.router, prefix="/api")
app.include_router(docs_content.router)

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


_PRIVACY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="index, follow" />
  <title>Privacy Policy — NEXUS by Gayo Sphere</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: #f8fafc; color: #1e293b;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.65; -webkit-font-smoothing: antialiased;
    }
    .wrap { max-width: 760px; margin: 0 auto; padding: 56px 24px 96px; }
    header { border-bottom: 1px solid #e2e8f0; padding-bottom: 24px; margin-bottom: 32px; }
    h1 { font-size: 1.9rem; margin: 0 0 6px; letter-spacing: -0.02em; }
    h2 { font-size: 1.18rem; margin: 38px 0 10px; letter-spacing: -0.01em; }
    p, li { font-size: 0.98rem; color: #334155; }
    a { color: #2563eb; }
    .muted { color: #64748b; font-size: 0.85rem; }
    ul { padding-left: 1.25rem; }
    li { margin: 6px 0; }
    code { background: #eef2f7; padding: 1px 6px; border-radius: 5px; font-size: 0.85em; }
    footer { margin-top: 48px; border-top: 1px solid #e2e8f0; padding-top: 20px; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>Privacy Policy</h1>
      <p class="muted">NEXUS — operated by Gayo Sphere &middot; Last updated: 20 June 2026</p>
    </header>

    <p>
      NEXUS (&ldquo;NEXUS&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;) provides an AI-assisted
      messaging and knowledge platform. This policy explains what data we process when a
      workspace owner connects a Facebook Page to NEXUS, how that data is used, retained,
      and deleted, and the rights available to end users.
    </p>

    <h2>1. Information We Process</h2>
    <ul>
      <li><strong>Facebook Page connection data.</strong> When you connect a Page, we receive
        and store your Page ID, Page name, profile picture URL, and a Page Access Token used
        to send and receive messages on your behalf.</li>
      <li><strong>Messaging content.</strong> Messages, comments, and conversation metadata
        delivered to us through Meta&rsquo;s webhooks so NEXUS can generate and send replies.</li>
      <li><strong>Account data.</strong> The email address and workspace details of the
        NEXUS user who authorizes the connection.</li>
    </ul>

    <h2>2. How We Use Facebook Data</h2>
    <ul>
      <li>To deliver the core service: receiving inbound messages/comments and sending
        automated or human-assisted replies through your connected Page.</li>
      <li>To display your connected Page&rsquo;s name and avatar inside the NEXUS dashboard so
        you can confirm the active connection.</li>
      <li>We use the granted permissions
        (<code>pages_show_list</code>, <code>pages_messaging</code>,
        <code>pages_manage_metadata</code>) solely for these purposes.</li>
    </ul>

    <h2>3. Data Storage &amp; Security</h2>
    <p>
      Page Access Tokens are encrypted at rest (AES-128-CBC with HMAC-SHA256 authentication,
      via Fernet) and are never written to application logs or exposed to the browser. Data
      is processed on access-controlled infrastructure and transmitted over TLS.
    </p>

    <h2>4. Data Sharing</h2>
    <p>
      <strong>We do not sell your data or any Facebook user data to third parties.</strong>
      Facebook data is not shared except with the infrastructure sub-processors strictly
      required to operate the service (e.g. hosting and the LLM provider used to generate
      replies), and only to the extent necessary to deliver the feature you enabled.
    </p>

    <h2>5. Data Retention</h2>
    <p>
      Connection data and message history are retained for as long as your Page remains
      connected and your workspace is active. When you disconnect a Page or delete your
      workspace, the associated Page binding and stored token are removed promptly.
    </p>

    <h2>6. Data Deletion</h2>
    <p>
      You may revoke NEXUS&rsquo;s access at any time from your
      <a href="https://www.facebook.com/settings?tab=business_tools" rel="noopener">Facebook
      Business Integrations</a> settings, or by disconnecting the Page inside the NEXUS
      Integrations dashboard. To request deletion of all data we hold about you or your Page,
      email <a href="mailto:privacy@gayo-sphere.cloud">privacy@gayo-sphere.cloud</a> and we
      will process the request within 30 days.
    </p>

    <h2>7. Meta Platform Compliance</h2>
    <p>
      Our use and transfer of information received from Meta APIs adheres to the
      <a href="https://developers.facebook.com/terms/" rel="noopener">Meta Platform Terms</a>
      and Developer Policies, including the limited-use requirements governing permissions.
    </p>

    <h2>8. Contact</h2>
    <p>
      Questions about this policy or your data can be sent to
      <a href="mailto:privacy@gayo-sphere.cloud">privacy@gayo-sphere.cloud</a>.
    </p>

    <footer>
      <p class="muted">&copy; 2026 Gayo Sphere. All rights reserved.</p>
    </footer>
  </div>
</body>
</html>"""


@app.get("/privacy", include_in_schema=False)
async def privacy() -> HTMLResponse:
    """Public privacy policy — required for Meta App Review.

    Served as a standalone, auth-free HTML document (Meta's reviewers must be
    able to reach it without logging in). Covers Facebook data usage, data
    deletion, retention, and the no-third-party-selling commitment.
    """

    return HTMLResponse(content=_PRIVACY_HTML)


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
