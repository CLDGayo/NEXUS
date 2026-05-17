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

    # ---- Embedding model ----
    # Phase 3 default matches the existing v1 Qdrant collection so live
    # retrieval works today. Phase 2's ingest_v2 will land jina-v2 + late
    # chunking under a new collection; flip both fields together to switch.
    embed_model: str = Field(default="BAAI/bge-small-en-v1.5")

    # ---- Retrieval tuning (Phase 3) ----
    retrieval_k_per_arm: int = Field(default=50, ge=1, le=200)
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    rerank_model: str = Field(default="jinaai/jina-reranker-v2-base-multilingual")

    # ---- Generation (Phase 3) ----
    generation_model: str = Field(default="groq-llama-3.3-70b")
    generation_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    generation_max_tokens: int = Field(default=1024, ge=64, le=8192)

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

    # ---- Facebook Messenger surface (Phase 8) ----
    messenger_public_enabled: bool = Field(default=False)
    messenger_app_secret: str | None = None
    messenger_verify_token: str | None = None
    messenger_page_access_token: str | None = None

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

    def outbound_backoff_seconds(self) -> list[int]:
        """Parse the CSV into ordered backoff intervals."""

        parts = [p.strip() for p in self.outbound_backoff_seconds_csv.split(",") if p.strip()]
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
