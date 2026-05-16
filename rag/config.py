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

    # ---- Outbound automation webhook (Phase 8) ----
    make_webhook_url: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Memoized accessor — `Settings()` is cheap but reading is cheaper."""

    return Settings()


settings = get_settings()
