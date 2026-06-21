"""Single source of environment configuration for the v2 cortex.

Phase 1 wires the chassis only. Phase 2+ modules import `settings` from here
rather than reading `os.environ` directly so secrets and endpoints have one
audit point.

Existing v1 modules continue to read `os.environ` via `python-dotenv`; this
file is additive and does not replace them.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed view of the runtime environment.

    All fields default to values that work inside the docker-compose network
    so a fresh `docker compose up` boots without `.env` overrides for local
    smoke tests. Production deployments must set the secrets explicitly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Vault ----
    vault_path: str = Field(default="/vault")

    # ---- Qdrant ----
    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_api_key: str | None = None
    qdrant_collection: str = Field(default="nexus-vault-v2")

    # ---- Postgres ----
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://nexus:nexus@postgres:5432/nexus"
    )

    # ---- Phase 27 — IAM (fastapi-users JWT) ----
    # Signs every access token issued by /api/auth/jwt/login. Must be set in
    # production (the lifespan boot guard fails fast if missing/short).
    # Tests stub a known-weak default via rag/conftest.py.
    nexus_jwt_secret: str = Field(default="", alias="NEXUS_JWT_SECRET")

    # ---- Redis ----
    redis_url: str = Field(default="redis://redis:6379/0")

    # ---- LLM gateway (LiteLLM proxy) ----
    litellm_base_url: str = Field(default="http://litellm:4000")
    litellm_master_key: str = Field(default="sk-litellm-change-me")

    # ---- Observability (Langfuse) ----
    langfuse_host: str = Field(default="http://langfuse-web:3000")
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    otel_exporter_otlp_endpoint: str = Field(default="http://otel-collector:4317")

    # ---- Phase 28 Part 2 — Minio (S3) object storage for avatars ----
    # Endpoint the FastAPI process talks to. In docker-compose the service is
    # named ``minio`` (host: ``minio:9000``); on the VPS the same container
    # is reachable as ``127.0.0.1:9000``; on Mac dev pointing at the VPS
    # tunnel set ``https://minio.nexus.gayo-sphere.cloud``.
    minio_endpoint: str = Field(default="http://minio:9000")
    # Credentials default to the docker-compose root user/password so a local
    # ``docker compose up`` boots without overrides. Production must set both.
    minio_access_key: str = Field(default="minio")
    minio_secret_key: str = Field(default="miniosecret")
    minio_region: str = Field(default="us-east-1")
    # Bucket holding ``{user_id}.webp`` avatar blobs. Provisioned once by
    # ``rag.scripts.phase28_bootstrap_minio``; the running service never
    # creates it on the fly.
    minio_bucket_avatars: str = Field(default="nexus-avatars")
    # Public-facing base URL (CDN / nginx subdomain) used to render the avatar
    # in the SPA. When set we store ``{minio_public_base_url}/{bucket}/{key}``
    # in ``app.users.profile_image_url`` so the browser can <img src> it
    # directly without going through the FastAPI process. When empty the
    # avatar router returns presigned URLs instead.
    minio_public_base_url: str = Field(default="")
    # Phase 32.4 — Public absolute origin for the running FastAPI app
    # (e.g. ``https://chat.nexus.gayo-sphere.cloud``). The messenger
    # carousel writes product image URLs that Meta's Send API has to
    # fetch from a public host; we mint signed ``object_proxy`` tokens
    # under ``/api/objects/{token}`` and prefix them with this base so
    # the URL is absolute. Empty in dev — the SPA hits same-origin and
    # the carousel branch logs + drops the image.
    nexus_public_base_url: str = Field(default="")
    # Avatar uploads: max bytes BEFORE Pillow normalisation. We resize down
    # to 256×256 WebP server-side, so this caps the raw client payload.
    avatar_max_upload_bytes: int = Field(
        default=2 * 1024 * 1024, ge=1, le=20 * 1024 * 1024
    )
    avatar_output_size: int = Field(default=256, ge=64, le=1024)

    # ---- Phase 32 — Product catalog (MinIO + Qdrant + Postgres) ----
    minio_bucket_products: str = Field(default="nexus-products")
    product_image_max_bytes: int = Field(
        default=5 * 1024 * 1024, ge=1, le=20 * 1024 * 1024
    )
    product_image_max_dim: int = Field(default=1200, ge=64, le=4096)
    product_max_images: int = Field(default=10, ge=1, le=50)
    product_cta_url_template: str = Field(default="")

    # ---- Embedding model ----
    # Phase 3 default matches the existing v1 Qdrant collection so live
    # retrieval works today. Phase 2's ingest_v2 will land jina-v2 + late
    # chunking under a new collection; flip both fields together to switch.
    embed_model: str = Field(default="BAAI/bge-small-en-v1.5")

    # ---- Retrieval tuning (Phase 3) ----
    retrieval_k_per_arm: int = Field(default=50, ge=1, le=200)
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    # Default to ms-marco-MiniLM-L-6-v2: 23MB single-file ONNX, fastembed-native,
    # loads in <2s on first call (vs. ~30s for jina-v2 multi-file ~700MB).
    # Switched 2026-05-21 after jina-v2 ONNX path failed to load post-fetch.
    # Multilingual notes can override via `RERANK_MODEL=BAAI/bge-reranker-base`.
    rerank_model: str = Field(default="Xenova/ms-marco-MiniLM-L-6-v2")

    # Persistent path for fastembed ONNX caches. Mounted as a docker volume
    # so containers don't re-download multi-hundred-MB models on every
    # restart (which blocked the event loop long enough to fail the
    # healthcheck on 2026-05-21).
    fastembed_cache_dir: str = Field(default="/home/nexus/.cache/fastembed")

    # ---- Generation (Phase 3) ----
    generation_model: str = Field(default="groq-llama-3.3-70b")
    generation_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    generation_max_tokens: int = Field(default=1024, ge=64, le=8192)
    # Phase 22 — fast, cheap model used for follow-up suggestions and the
    # history-aware coreference rewriter. ~10x cheaper than the 70B main
    # generation model and ~150ms per call, so it can run on every
    # multi-turn request without blowing the latency budget.
    followup_model: str = Field(default="groq-llama-3.1-8b")

    # ---- Multimodal / vision (Phase 15) ----
    vision_model: str = Field(
        default="groq-llama-4-scout",
        description=(
            "LiteLLM alias used when a request includes image attachments. "
            "Routes to a vision-capable model in litellm/config.yaml."
        ),
    )
    vision_max_attachments: int = Field(default=4, ge=1, le=8)
    vision_upload_max_bytes: int = Field(
        default=5 * 1024 * 1024, ge=1, le=20 * 1024 * 1024
    )

    # ---- Phase 16: PDF image captioning ----
    vision_pdf_max_images: int = Field(default=20, ge=0, le=200)
    vision_pdf_concurrency: int = Field(default=4, ge=1, le=16)
    vision_pdf_caption_max_tokens: int = Field(default=256, ge=64, le=1024)
    vision_pdf_min_dimension: int = Field(default=64, ge=0, le=4096)
    vision_pdf_min_bytes: int = Field(default=2048, ge=0, le=1_048_576)
    vision_pdf_v2_enabled: bool = Field(default=False)

    # ---- Phase 24: Agentic iterative plan-and-solve loop ----
    # Hard cap on research-mode loop iterations. The loop_decision node
    # forces exit when ``research_iterations >= research_max_iterations``
    # regardless of how many sub-queries the planner emitted, so this is
    # the single termination guarantee that defends the pipeline from a
    # mis-behaving planner LLM returning an unbounded list.
    research_max_iterations: int = Field(default=3, ge=1, le=5)
    # Per-iteration rerank top_k for research mode. Three iterations × 4
    # chunks = 12 chunks max in ``accumulated_context`` after dedup, which
    # keeps the synthesis prompt under the existing 1024-token generation
    # budget (vs. retrieval_top_k=8 which would 3× the envelope).
    research_subquery_top_k: int = Field(default=4, ge=1, le=20)

    # ---- LangGraph checkpointer (Phase 3) ----
    # ``memory`` is the default for local dev and tests; switch to
    # ``postgres`` in production (requires `await saver.setup()` once).
    langgraph_checkpoint: str = Field(default="memory")

    # ---- Phase 4 ingest pipeline ----
    # Late-chunker model. 768-dim, 8192-token context, supports ALiBi.
    ingest_embed_model: str = Field(default="jinaai/jina-embeddings-v2-base-en")
    ingest_embed_dim: int = Field(default=768, ge=1)
    ingest_max_tokens: int = Field(default=8192, ge=64, le=32768)
    ingest_qdrant_collection: str = Field(default="nexus-vault-v2")

    # Semantic chunker (chonkie SemanticChunker).
    semantic_chunker_model: str = Field(default="minishlab/potion-base-8M")
    semantic_break_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    ingest_chunk_size: int = Field(default=400, ge=32, le=2048)

    # ---- Webhook surface (Phase 2) ----
    webhook_api_key: str | None = Field(
        default=None,
        description="Shared secret n8n/Make must send as X-Webhook-Api-Key.",
    )

    # ---- Webhook hardening (Phase 7) ----
    messenger_rate_limit_per_min: int = Field(
        default=20,
        ge=0,
        le=10_000,
        description="Max inbound messages per rolling 60s window per user_id. 0 disables.",
    )
    messenger_idempotency_ttl_s: int = Field(
        default=86_400,
        ge=60,
        le=604_800,
        description="TTL for the SET-NX idempotency key (seconds).",
    )
    # Phase 21 — webhook coalescing window. Events from the same sender
    # within this many seconds collapse into one logical turn before any
    # idempotency / lock / dispatch work runs. Wide enough to absorb
    # Meta's split between an image event and its caption text event,
    # narrow enough that a deliberate follow-up stays a separate turn.
    messenger_coalesce_window_s: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Seconds within which inbound events from the same sender are merged into one turn.",
    )
    # Phase 21 — shutdown drain. Lifespan awaits in-flight messenger
    # background tasks up to this many seconds before tearing down the
    # Postgres checkpointer pool. Survivors are cancelled.
    messenger_shutdown_drain_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=300.0,
        description="Max seconds to wait for in-flight messenger tasks during shutdown.",
    )

    # ---- Facebook Messenger surface (Phase 8) ----
    messenger_public_enabled: bool = Field(default=False)
    messenger_app_secret: str | None = None
    messenger_verify_token: str | None = None
    messenger_page_access_token: str | None = None

    # Phase 37 — Facebook App ID. Used by HITL to distinguish a human-owner
    # echo (sent via Page Inbox / Business Suite; has no app_id OR a
    # different app_id) from our bot's own outbound echo (carries this
    # exact app_id). Found in Meta App Dashboard > Settings > Basic.
    messenger_app_id: str | None = None

    # ---- Outbound automation webhook (Phase 6 — n8n / Make delivery) ----
    make_webhook_url: str | None = None
    outbound_dispatch_enabled: bool = Field(default=False)
    outbound_send_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    outbound_max_attempts: int = Field(default=4, ge=1, le=10)
    # Comma-separated seconds for retry delays: e.g. "30,120,600,3600"
    outbound_backoff_seconds_csv: str = Field(default="30,120,600,3600")
    outbound_queue_key: str = Field(default="nexus:outbound:scheduled")
    outbound_dlq_key: str = Field(default="nexus:outbound:dead")
    outbound_worker_poll_seconds: float = Field(default=2.0, gt=0.0, le=60.0)
    outbound_worker_batch_size: int = Field(default=16, ge=1, le=256)

    # ---- Phase 34 — n8n sales webhook endpoints ----
    # Checkout: n8n receives product+qty, calls Stripe, returns session URL.
    # Lead:     n8n receives email, pushes to GoHighLevel CRM.
    # Both default to None so the system boots without them configured.
    n8n_webhook_checkout_url: str | None = None
    n8n_webhook_lead_url: str | None = None

    # Phase 36 — Customer profile enrichment via GoHighLevel CRM.
    # n8n receives ``{ sender_id }`` and returns the CRM contact record
    # (name, lifetime_spend, last_order_date, tags, segment, etc.).
    # Defaults to None so the system boots without it configured;
    # ``enrich_customer_profile_node`` short-circuits on unset.
    n8n_webhook_profile_url: str | None = None

    # Phase 37 — HITL owner notification webhook.
    # n8n receives { sender_id, page_id, thread_key, user_query, bot_answer }
    # and pushes a notification to the owner (email / Slack / SMS).
    # Defaults to None so the system boots without it configured.
    n8n_webhook_notify_url: str | None = None

    # Phase 51 — workspace invite emails via n8n.
    # n8n receives { email, workspace_name, invite_link, role } and delivers
    # the invite email. Defaults to None so the system boots without it;
    # create_invite skips the n8n POST when unset.
    n8n_webhook_invite_url: str | None = None

    # Phase 37 — how long (seconds) the bot pauses after the human owner
    # reads or replies in the thread. Default 3600 = 1 hour. TTL-backed
    # via Redis so the pause auto-clears without a cron / cleanup job.
    hitl_pause_duration_s: int = Field(default=3600, ge=60, le=86400)

    # Phase 38 — Public comment triage engine.
    # Enables the stateless LLM-based triage of public Facebook Page comments.
    # When False, feed/comment webhook events are silently dropped (200 OK).
    comment_triage_enabled: bool = Field(default=False)

    # Phase 57 — Facebook Comment-to-Message automation engine.
    # When True (default), feed/comment/add events are enqueued as
    # ``fb_private_reply`` jobs. The worker runs keyword matching first and
    # falls back to the LLM triage path on no-match (coexistence mode).
    # Set to False to disable automations and fall back to the plain
    # ``comment_triage_enabled`` path for back-compat.
    fb_automations_enabled: bool = Field(default=True)

    # Phase 58 — NEXUS Flow visual automation engine.
    # When True, inbound feed/comment/add events are dispatched to the
    # stateful flow traversal engine (``fb_flow`` worker target).  Active
    # flows are matched first; no-match falls through to the Phase 57
    # ``fb_private_reply`` engine (coexist with precedence).
    # Default False — zero behaviour change until a tenant activates a flow.
    nexus_flows_enabled: bool = Field(default=False)

    # ---- Phase 55/56 — token encryption at rest ----
    # urlsafe-base64 32-byte Fernet key. Encrypts Facebook page/user tokens and
    # Google OAuth access tokens before they touch Postgres. Empty in dev/tests;
    # rag.crypto raises if a code path actually needs it while unset.
    nexus_token_encryption_key: str = Field(
        default="", alias="NEXUS_TOKEN_ENCRYPTION_KEY"
    )

    # ---- Phase 55 — Facebook Page metadata sync ----
    # Master switch for the page-field webhook branch + sync worker path. When
    # False the webhook ignores name/about/picture changes (200 OK) and no
    # Graph API metadata fetches are scheduled.
    facebook_sync_enabled: bool = Field(default=False)
    facebook_graph_version: str = Field(default="v21.0")
    # Redis key the sync jobs share with the existing outbound queue machinery.
    facebook_sync_correlation_prefix: str = Field(default="fb_sync")

    # ---- Phase 61 — One-click Meta OAuth (Page connect) ----
    # Standard Facebook Login app credentials. The redirect URI MUST be
    # whitelisted byte-for-byte in the Meta App dashboard ("Valid OAuth
    # Redirect URIs"), e.g. https://chat.nexus.gayo-sphere.cloud/api/facebook/callback
    facebook_app_id: str | None = None
    facebook_app_secret: str | None = None
    facebook_redirect_uri: str | None = None

    # ---- Phase 56 — Google SSO (OIDC authorization-code + PKCE) ----
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Absolute callback URL registered in the Google Cloud console, e.g.
    # https://chat.nexus.gayo-sphere.cloud/api/auth/google/callback
    google_redirect_uri: str | None = None
    # Short-lived server-side CSRF/nonce/PKCE state lifetime (seconds).
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    # Rotating refresh-cookie lifetime (days). Access JWT stays 1h (auth/config).
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    # When True, an OAuth login whose email domain matches an existing
    # tenant.domain creates a pending domain_join_request instead of silently
    # provisioning a brand-new workspace. Admin approval grants membership.
    domain_autojoin_enabled: bool = Field(default=True)
    # Set Secure flag on the refresh cookie. True in prod (HTTPS); tests/dev
    # over http need it False or the cookie is dropped.
    refresh_cookie_secure: bool = Field(default=True)

    # ---- Security headers + CORS hardening (ZAP 2026-06-20 remediation) ----
    # Cross-Domain Misconfiguration: the legacy ``allow_origins=["*"]`` (paired
    # with ``allow_credentials=True``, which browsers reject anyway) let any
    # origin read API responses. Lock CORS to an explicit allowlist. The SPA
    # and the embeddable widget both call the API same-origin (relative URLs),
    # so the only genuine cross-origin callers are local Vite dev servers.
    # Override on the VPS via ``CORS_ALLOW_ORIGINS`` if a new origin is added.
    cors_allow_origins_csv: str = Field(
        default=(
            "https://chat.nexus.gayo-sphere.cloud,"
            "https://nexus.gayo-sphere.cloud,"
            "http://localhost:5173,"
            "http://127.0.0.1:5173"
        ),
        alias="CORS_ALLOW_ORIGINS",
        description="Comma-separated CORS origin allowlist. Replaces wildcard.",
    )
    # Master switch for the response security-headers middleware (CSP, HSTS,
    # X-Content-Type-Options, Referrer-Policy, etc.). True in prod; tests flip
    # it as needed.
    security_headers_enabled: bool = Field(default=True)
    # HSTS max-age (seconds). 2 years + includeSubDomains is the
    # preload-eligible baseline. Only emitted over HTTPS requests.
    hsts_max_age: int = Field(default=63_072_000, ge=0, le=63_072_000)
    # Content-Security-Policy for the SPA / API surface. Kept env-overridable
    # so ops can relax a directive without a code redeploy if the Vite bundle
    # ever needs an additional source. ``frame-ancestors 'self'`` stops the
    # admin SPA being framed; the embeddable widget gets its own policy below.
    security_csp: str = Field(
        default=(
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'"
        ),
        alias="SECURITY_CSP",
        description="Content-Security-Policy header value for app/API routes.",
    )
    # Widget CSP — identical hardening but ``frame-ancestors *`` so the chat
    # widget remains embeddable as an iframe on arbitrary customer sites.
    # Tighten to a specific customer-domain allowlist via ``SECURITY_CSP_WIDGET``
    # once the embed list is known.
    security_csp_widget: str = Field(
        default=(
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors *"
        ),
        alias="SECURITY_CSP_WIDGET",
        description="CSP for embeddable widget routes (permits cross-site framing).",
    )

    def cors_allow_origins(self) -> list[str]:
        """Parse the CSV allowlist into a de-duplicated, ordered origin list."""

        seen: set[str] = set()
        out: list[str] = []
        for part in self.cors_allow_origins_csv.split(","):
            origin = part.strip().rstrip("/")
            if origin and origin not in seen:
                seen.add(origin)
                out.append(origin)
        return out

    def outbound_backoff_seconds(self) -> list[int]:
        """Parse the CSV into ordered backoff intervals."""

        parts = [
            p.strip() for p in self.outbound_backoff_seconds_csv.split(",") if p.strip()
        ]
        out: list[int] = []
        for part in parts:
            try:
                value = int(part)
            except ValueError:
                continue
            if value > 0:
                out.append(value)
        return out or [30, 120, 600, 3600]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Memoized accessor — `Settings()` is cheap but reading is cheaper."""

    return Settings()


settings = get_settings()
