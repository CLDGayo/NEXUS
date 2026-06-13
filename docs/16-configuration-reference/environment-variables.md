# Environment Variables

Complete reference for all static environment variables in `rag/config.py`. Set these in `rag/.env` (local dev) or `/home/nexus-rag/.env` (VPS prod).

**Required** = server fails to start or core features break without this value.
**Optional** = feature degrades gracefully when absent.

---

## Vault

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `VAULT_PATH` | `str` | — | ✅ | Absolute path to the Obsidian vault directory. Used by the ingest pipeline and file watcher. |

---

## Qdrant (Vector Store)

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `QDRANT_URL` | `str` | `http://localhost:6333` | ✅ | Qdrant server URL. Mac dev: use public HTTPS. VPS prod: use `http://127.0.0.1:6333`. |
| `QDRANT_API_KEY` | `str` | `""` | Prod only | Qdrant API key. Required when Qdrant is exposed via public HTTPS. Empty = no auth (dev Docker). |
| `QDRANT_COLLECTION` | `str` | `nexus-vault` | ✅ | Collection name for all vault chunks. Must match the collection created on first ingest. |

---

## PostgreSQL

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `POSTGRES_DSN` | `str` | — | ✅ | Async DSN: `postgresql+asyncpg://user:password@host:port/database`. Used by SQLAlchemy engine and Alembic. |

---

## Redis

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `REDIS_URL` | `str` | `redis://localhost:6379` | ✅ | Redis connection URL. Used for HITL pause keys, Messenger retry queue, rate-limit counters, and session cache. |

---

## Authentication & JWT

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `NEXUS_JWT_SECRET` | `str` | — | ✅ | Secret key for JWT signing. Minimum 32 bytes. Rotate with `POST /api/settings/rotate-jwt` (owner only). |
| `NEXUS_PASSWORD` | `str` | — | Optional | Legacy admin password (v1 auth). Deprecated. Use fastapi-users JWT login instead. |

---

## LLM Generation (Groq)

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `GROQ_API_KEY` | `str` | — | ✅ | Groq Cloud API key. All chat endpoints fail without this. |
| `GROQ_MODEL` | `str` | `llama-3.3-70b-versatile` | Optional | Primary generation model ID. Overridable per-tenant via AI settings. |
| `FOLLOWUP_MODEL` | `str` | `llama-3.1-8b-instant` | Optional | Model used for fast follow-up question generation (3 suggestions per turn). |

---

## LiteLLM Proxy

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `LITELLM_BASE_URL` | `str` | — | Optional | Base URL of the LiteLLM proxy (e.g., `http://litellm:4000`). When set, routes all LLM calls through LiteLLM for multi-provider routing. |
| `LITELLM_MASTER_KEY` | `str` | — | Optional | Master API key for the LiteLLM proxy. Required when `LITELLM_BASE_URL` is set. |

---

## Embeddings & Models

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `EMBED_MODEL` | `str` | `BAAI/bge-small-en-v1.5` | Optional | fastembed model for dense retrieval queries. 384-dim cosine. Downloaded to `FASTEMBED_CACHE_DIR` on first use. |
| `INGEST_EMBED_MODEL` | `str` | `jinaai/jina-embeddings-v2-base-en` | Optional | Late chunking embedding model for ingest v2. 768-dim, 8192-token context. |
| `FASTEMBED_CACHE_DIR` | `str` | `~/.cache/fastembed` | Optional | Directory where fastembed downloads ONNX model files. On VPS: `/home/nexus/.cache/fastembed`. The actual on-disk directory for `BAAI/bge-small-en-v1.5` resolves to `models--qdrant--bge-small-en-v1.5-onnx-q` — do not rely on predicting the cache path from the model ID. |
| `RERANK_MODEL` | `str` | `Xenova/ms-marco-MiniLM-L-6-v2` | Optional | Cross-encoder model for reranking (fastembed TextCrossEncoder). |
| `VISION_MODEL` | `str` | `llama-3.2-11b-vision-preview` | Optional | Vision model for image captioning in multimodal ingest. |

---

## Retrieval Parameters (static defaults — override via dynamic settings)

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `RETRIEVAL_K_PER_ARM` | `int` | `50` | Optional | Candidates retrieved per arm (dense / sparse / graph) before RRF fusion. Corresponds to dynamic `RETRIEVE_K`. |
| `RETRIEVAL_TOP_K` | `int` | `6` | Optional | Final chunks passed to the LLM after reranking. Corresponds to dynamic `TOP_K`. |

---

## MinIO / S3 Object Storage

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `MINIO_ENDPOINT` | `str` | — | Optional | MinIO server endpoint (e.g., `minio:9000`). Required for avatar and product image uploads. |
| `MINIO_ACCESS_KEY` | `str` | — | Optional | MinIO access key ID. |
| `MINIO_SECRET_KEY` | `str` | — | Optional | MinIO secret access key. |
| `MINIO_BUCKET_AVATARS` | `str` | `nexus-avatars` | Optional | Bucket name for workspace and user avatars (WebP). |
| `MINIO_BUCKET_PRODUCTS` | `str` | `nexus-products` | Optional | Bucket name for product images. |
| `MINIO_PUBLIC_BASE_URL` | `str` | — | Optional | Public URL prefix for MinIO objects (e.g., `https://assets.nexus.gayo-sphere.cloud`). Used to generate presigned CDN URLs. |

---

## Meta Messenger

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `MESSENGER_PUBLIC_ENABLED` | `bool` | `false` | Optional | Master switch for Messenger webhook. Set to `true` to activate inbound message processing. |
| `MESSENGER_APP_ID` | `str` | — | Optional | Meta App ID. Used to distinguish bot echoes from human Page Inbox echoes. |
| `MESSENGER_APP_SECRET` | `str` | — | Optional | Meta App Secret. Used for HMAC SHA-256 webhook signature verification. |
| `MESSENGER_VERIFY_TOKEN` | `str` | — | Optional | Webhook verification token set in Meta App Dashboard. |
| `MESSENGER_PAGE_ACCESS_TOKEN` | `str` | — | Optional | Default Page Access Token for outbound replies. Can be rotated via API without restart. |
| `MESSENGER_RATE_LIMIT_PER_MIN` | `int` | `60` | Optional | Per-sender message rate limit (messages per minute). Excess messages are dropped. |
| `MESSENGER_COALESCE_WINDOW_MS` | `int` | `1500` | Optional | Window in milliseconds to coalesce rapid sequential messages from the same sender into a single request. |
| `MESSENGER_SHUTDOWN_DRAIN_S` | `int` | `5` | Optional | Seconds to allow the outbound retry queue to drain on graceful shutdown. |
| `HITL_PAUSE_DURATION_S` | `int` | `3600` | Optional | Duration in seconds for HITL pause (bot silenced after human handover). Default: 1 hour. |

---

## n8n / Make Webhooks (Outbound Automation)

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `N8N_WEBHOOK_CHECKOUT_URL` | `str` | — | Optional | n8n webhook for generating Stripe Checkout links (SDR `generate_checkout_link` tool). |
| `N8N_WEBHOOK_LEAD_URL` | `str` | — | Optional | n8n webhook for CRM lead capture (SDR `capture_lead` tool → GoHighLevel). |
| `N8N_WEBHOOK_NOTIFY_URL` | `str` | — | Optional | n8n webhook for HITL owner notifications (fires once per 24h per sender). |
| `N8N_WEBHOOK_INVITE_URL` | `str` | — | Optional | n8n webhook for workspace invite emails. |
| `N8N_WEBHOOK_PROFILE_URL` | `str` | — | Optional | n8n webhook for profile update notifications. |
| `MAKE_WEBHOOK_URL` | `str` | — | Optional | Make.com webhook alternative to n8n for outbound dispatch. |
| `OUTBOUND_DISPATCH_ENABLED` | `bool` | `true` | Optional | Master switch for all outbound n8n/Make webhook calls. Set to `false` in test environments. |

---

## LangGraph Checkpointer

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `LANGGRAPH_CHECKPOINT` | `str` | `memory` | Optional | Checkpointer backend: `memory` (in-process, no persistence) or `postgres` (durable multi-turn state via `POSTGRES_DSN`). Use `postgres` in production. |

---

## Ingest Pipeline

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `INGEST_CHUNK_SIZE` | `int` | `400` | Optional | Target token count per chunk (tiktoken cl100k). |
| `INGEST_CHUNK_OVERLAP` | `int` | `50` | Optional | Token overlap between adjacent chunks. |
| `SEMANTIC_BREAK_THRESHOLD` | `float` | `0.55` | Optional | Cosine similarity floor between sentences. Drops below this → chunk boundary. |
| `INGEST_MAX_TOKENS` | `int` | `8192` | Optional | Maximum document token length before the ingest pipeline splits to multiple segments. |

---

## Vision / Multimodal

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `VISION_MAX_ATTACHMENTS` | `int` | `4` | Optional | Maximum images per chat message. |
| `VISION_UPLOAD_MAX_BYTES` | `int` | `10485760` | Optional | Maximum upload size per image (default: 10 MB). |
| `VISION_PDF_MAX_IMAGES` | `int` | `20` | Optional | Maximum pages to render from a PDF during vision-based ingest. |
| `VISION_PDF_CONCURRENCY` | `int` | `4` | Optional | Parallel page rendering workers for PDF vision ingest. |
| `VISION_PDF_CAPTION_TOKENS` | `int` | `256` | Optional | Max tokens per page caption during vision ingest. |

---

## Research Mode

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `RESEARCH_MAX_ITERATIONS` | `int` | `3` | Optional | Maximum sub-query iterations in research mode before forcing generation. |
| `RESEARCH_SUBQUERY_TOP_K` | `int` | `3` | Optional | Chunks retrieved per sub-query in research mode. |

---

## OpenTelemetry

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `str` | — | Optional | OTLP gRPC endpoint for trace export (e.g., `http://otel-collector:4317`). When absent, OTel traces are silently discarded. |
| `OTEL_SERVICE_NAME` | `str` | `nexus-rag` | Optional | Service name tag on all exported spans. |

---

## Langfuse (LLM Observability)

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `LANGFUSE_HOST` | `str` | `https://cloud.langfuse.com` | Optional | Langfuse server URL. Self-hosted or cloud. |
| `LANGFUSE_PUBLIC_KEY` | `str` | — | Optional | Langfuse project public key. When absent, Langfuse is disabled (no-op). |
| `LANGFUSE_SECRET_KEY` | `str` | — | Optional | Langfuse project secret key. Required when `LANGFUSE_PUBLIC_KEY` is set. |

---

## Comment Triage

| Variable | Type | Default | Required | Description |
|---|---|---|---|---|
| `COMMENT_TRIAGE_ENABLED` | `bool` | `true` | Optional | Enables LLM-powered Facebook comment triage. Disable to pass all comments directly to the AI without classification. |

---

## Example `.env` (Local Development)

```bash
# Vault
VAULT_PATH=/Users/yourname/Obsidian/MyVault

# Database
POSTGRES_DSN=postgresql+asyncpg://nexus:nexus@localhost:5432/nexus

# Vector store
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=nexus-vault

# Cache
REDIS_URL=redis://localhost:6379

# Auth
NEXUS_JWT_SECRET=your-minimum-32-character-secret-here

# LLM
GROQ_API_KEY=gsk_your_groq_key_here
GROQ_MODEL=llama-3.3-70b-versatile
FOLLOWUP_MODEL=llama-3.1-8b-instant

# LangGraph (use postgres in production)
LANGGRAPH_CHECKPOINT=memory
```

---

## Related Docs

- [Dynamic Settings](dynamic-settings.md) — live-tunable retrieval + generation parameters
- [Deployment Environment Setup](../12-deployment/environment-setup.md) — VPS `.env` management
- [Quickstart Guide](../01-getting-started/quickstart.md) — minimal env for first run
