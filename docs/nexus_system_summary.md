# Nexus — System Summary

> **Last updated:** 2026-05-19
> **Live surface (v2):** https://chat.nexus.gayo-sphere.cloud — Docker compose stack, LangGraph orchestrator
> **Messenger surface (v2):** https://messenger.nexus.gayo-sphere.cloud
> **v1 status:** ❌ Decommissioned — systemd `nexus-chat.service` stopped + disabled 2026-05-19 as part of Phase 9 cutover
> **Owner:** Clarence Lloyd Gayo
> **Vault root:** `/Users/clarencelloydgayo/Gayo Sphere/Second Brain Nexus`
> **Published vault:** https://nexus.gayo-sphere.cloud (Quartz v4, unaffected by cutover)

This is the canonical "what Nexus is right now" reference. It sits
between [README.md](../README.md) (public surface) and
[CLAUDE.md](../CLAUDE.md) (agent operating manual). For the original
pre-cutover deployment runbook see
[docs/phase8-cutover.md](./phase8-cutover.md).

---

## System Identity

| System | Surface | Engine | Status |
|---|---|---|---|
| **Nexus v1** | `chat.nexus.gayo-sphere.cloud` (legacy) | FastAPI + linear `rag.chat` pipeline, systemd `nexus-chat.service` on `127.0.0.1:8501` | ❌ **Decommissioned** (2026-05-19) |
| **Nexus v2** | `chat.nexus.gayo-sphere.cloud` + `messenger.nexus.gayo-sphere.cloud` | docker-compose stack, LangGraph orchestrator, LiteLLM gateway, Langfuse observability | ✅ **Production** |

Phase 9 cutover (2026-05-19):

- nginx vhost `chat.nexus.gayo-sphere.cloud` `proxy_pass` retargeted
  from `http://127.0.0.1:8501` (v1 systemd) → `http://127.0.0.1:8210`
  (v2 docker `api` container :8000).
- `systemctl disable --now nexus-chat` on the VPS. Unit file remains
  on disk for emergency rollback; binary path intact.
- SPA streams end-to-end through the LangGraph orchestrator. The
  Messenger surface continues to share the same `api` container.

---

## 1. RAG Chat Engine (v1 — Decommissioned)

> Retired 2026-05-19 as part of Phase 9. Code remains in tree for
> architectural reference; nginx no longer routes to it; the systemd
> unit is disabled.

The original linear chat pipeline:

- [rag/chat.py](../rag/chat.py) — SSE endpoint, directly called Groq with
  retrieved context; emitted `status` → `sources` → `token` → `followups`
  → `done` events.
- [rag/query.py](../rag/query.py) — embed query → Qdrant cosine search
  on collection `nexus-vault` → rank by score → return top-K chunks.
- [rag/ingest.py](../rag/ingest.py) — Markdown header walker, 400-token
  chunks with 50-token overlap (tiktoken cl100k), bge-small-en-v1.5
  embeddings, batched upsert to Qdrant.
- [rag/watcher.py](../rag/watcher.py) — watchdog file-system observer
  with 3 s debounce, triggered single-file re-ingest.
- Served by `nexus-chat.service` (`uvicorn app:app --host 127.0.0.1
  --port 8501`) on the VPS, behind nginx + Let's Encrypt.

What it shipped: SSE streaming, citation enforcement at prompt level,
follow-up question generation via `llama-3.1-8b-instant`, JWT auth,
SPA, conversation persistence, integrations webhooks, prompt library,
settings + changelog + logs surfaces.

What it never shipped (the gap that justified v2): BM25 hybrid
retrieval, cross-encoder reranking, late chunking, semantic chunk
boundaries, wikilink graph expansion, multi-step orchestration,
guardrails layer, LLM provider abstraction, structured tracing.

## 2. LangGraph Orchestrator (v2 — Production)

Active engine powering the SPA chat (`chat.nexus.gayo-sphere.cloud`)
and the Messenger surface (`messenger.nexus.gayo-sphere.cloud`).

- [rag/orchestrator/graph.py](../rag/orchestrator/graph.py) — graph
  definition; nodes wired in fixed order with conditional edges for
  rewrite / abstention loops.
- [rag/orchestrator/nodes.py](../rag/orchestrator/nodes.py) — node
  implementations: query parse, hybrid retrieve, rerank, graph expand,
  generate, self-grade, regenerate.
- [rag/orchestrator/state.py](../rag/orchestrator/state.py) — typed
  state object passed between nodes; carries query, candidates,
  scores per stage, citations, trace IDs.
- [rag/orchestrator/llm.py](../rag/orchestrator/llm.py) — LLM client
  bound to the LiteLLM gateway (never talks to provider SDKs directly).
- [rag/orchestrator/prompts/](../rag/orchestrator/prompts/) — system
  + user prompt templates, versioned per model family.

Query → graph → streaming SSE response is the single execution path
for both surfaces; the chat router and the Messenger worker both call
the same compiled graph.

## 3. Ingestion Pipelines

### v1 ingestion (Decommissioned)

> Retired 2026-05-19. Files remain in tree.

[rag/ingest.py](../rag/ingest.py) + [rag/watcher.py](../rag/watcher.py).
Header-aware split, 400/50 token chunking, bge-small-en-v1.5
(384-dim), Qdrant collection `nexus-vault`. Metadata extracted: file,
folder, title, heading_path, tags, content_hash, chunk_index,
chunk_total. Missing: wikilinks index, aliases, source_kind,
language, semantic boundary detection, code-fence preservation.

### v2 ingestion (Production)

[rag/ingest_v2/](../rag/ingest_v2/) package, exposed via
`python -m rag.ingest_v2`. Run on the VPS as
`docker compose exec api python -m rag.ingest_v2 ingest --vault -v`.

| Module | Role |
|---|---|
| [semantic_chunker.py](../rag/ingest_v2/semantic_chunker.py) | Sliding-window cosine similarity over adjacent sentence embeddings; cuts where similarity dips below `SEMANTIC_BREAK_THRESHOLD` |
| [late_chunker.py](../rag/ingest_v2/late_chunker.py) | Late-chunking pass — embeds long context once, then derives chunk vectors from token spans so chunks inherit surrounding semantics |
| [multimodal.py](../rag/ingest_v2/multimodal.py) | Image + PDF asset handling (vault attachments) |
| [metadata.py](../rag/ingest_v2/metadata.py) | Frontmatter parse, tag extraction, wikilink scan, source_kind classification, language detect, content_hash |
| [graph_db.py](../rag/ingest_v2/graph_db.py) | SQLite-backed wikilink graph (`rag/data/nexus_graph.db`) |
| [graph_index.py](../rag/ingest_v2/graph_index.py) | Builds `edges` + `nodes` tables; one-hop lookup helper for the retrieval graph node |
| [qdrant_writer.py](../rag/ingest_v2/qdrant_writer.py) | Idempotent upsert into collection `nexus-vault-v2`; collection-init via `init-collection` subcommand |
| [pipeline.py](../rag/ingest_v2/pipeline.py) | Orchestrates the per-file pass: parse → chunk → embed → write Qdrant + write graph |
| [cli.py](../rag/ingest_v2/cli.py) | CLI surface: `init-collection`, `ingest --vault`, `ingest --file`, `--changed` |
| [types.py](../rag/ingest_v2/types.py) | Typed dataclasses for chunks, metadata, ingestion results |

Vault is bind-mounted read-only at `/vault` inside the `api`
container (`/home/nexus-vault:/vault:ro`).

## 4. Retrieval Stack (v2)

[rag/retrieval/](../rag/retrieval/) — the hybrid retrieval and
reranking layer called by the orchestrator's retrieve nodes.

| Module | Role |
|---|---|
| [dense.py](../rag/retrieval/dense.py) | Dense cosine search against Qdrant `nexus-vault-v2` |
| [sparse.py](../rag/retrieval/sparse.py) | BM25 over the same chunk corpus; tokenization aligned with the embedding tokenizer |
| [rrf.py](../rag/retrieval/rrf.py) | Reciprocal Rank Fusion (`score = Σ 1 / (k + rank)`, k=60) — fuses sparse + dense candidate sets |
| [rerank.py](../rag/retrieval/rerank.py) | Cross-encoder reranker over the fused top-50 → returns top-K (default 6) |
| [graph.py](../rag/retrieval/graph.py) | One-hop expansion across the SQLite wikilink graph for multi-hop queries |
| [types.py](../rag/retrieval/types.py) | Candidate / scored-chunk dataclasses; per-stage score fields preserved end-to-end for trace logging |

Every chunk that survives the reranker carries `bm25_rank`,
`dense_rank`, `rrf_score`, `rerank_score` — all four make it into the
trace record.

## 5. LLM Gateway — LiteLLM (Production)

- Docker service `litellm` (see [docker-compose.yml](../docker-compose.yml)),
  config at [litellm/config.yaml](../litellm/config.yaml) (lite variant:
  [litellm/config.lite.yaml](../litellm/config.lite.yaml)).
- Single uvicorn worker bound to 1.5 G memory; healthcheck via
  `/health/liveliness` (override in
  [docker-compose.prod.yml](../docker-compose.prod.yml)).
- Master key + salt sourced from `.env.prod` (`LITELLM_MASTER_KEY`,
  `LITELLM_SALT_KEY`).
- Routes Groq (`llama-3.3-70b-versatile` primary,
  `llama-3.1-8b-instant` follow-ups), OpenAI, Anthropic — providers
  configured per-model in `config.yaml`.
- Every orchestrator / Messenger LLM call goes through LiteLLM —
  there are no direct provider SDK imports in the v2 graph.

## 6. Guardrails Layer (v2)

[rag/guardrails/](../rag/guardrails/) — invoked by the orchestrator
before streaming the answer to the user.

| Module | Role |
|---|---|
| [validators.py](../rag/guardrails/validators.py) | Schema / format / length validators on the generated answer |
| [groundedness.py](../rag/guardrails/groundedness.py) | Checks every factual sentence carries a `[n]` citation that resolves to a retrieved chunk |
| [entropy.py](../rag/guardrails/entropy.py) | Detects low-information / repetitive output |
| [handover.py](../rag/guardrails/handover.py) | Triggers honest abstention or human handover when retrieval confidence is below floor |
| [pipeline.py](../rag/guardrails/pipeline.py) | Composes the guardrail stages into a single check executed by the self-grade node |

Self-grade failure → one regeneration attempt; persistent failure →
abstention with an explanation, never a hallucination.

## 7. Messenger Integration (v2 — Production)

[rag/messenger/](../rag/messenger/) — Facebook Messenger surface
backed by an n8n bridge.

| Module | Role |
|---|---|
| [worker.py](../rag/messenger/worker.py) | Background worker (`python -m rag.messenger.worker`) running as docker service `outbound_worker`; drains the Redis queue and posts replies |
| [sender.py](../rag/messenger/sender.py) | Outbound dispatch — POSTs to the n8n "Outbound Listener" webhook |
| [idempotency.py](../rag/messenger/idempotency.py) | De-dupes inbound messages by `correlation_id` (Redis keyed) |
| [ratelimit.py](../rag/messenger/ratelimit.py) | App-level per-user rate limiting (env: `MESSENGER_RATE_LIMIT_PER_MIN`) |
| [pii.py](../rag/messenger/pii.py) | Redacts emails + Luhn-valid card numbers to `[EMAIL_REDACTED]` / `[CARD_REDACTED]` |
| [security.py](../rag/messenger/security.py) | API-key gate on the `/webhook/messenger/inbound` route — Facebook's `X-Hub-Signature-256` HMAC is validated by n8n, not FastAPI |
| [queue.py](../rag/messenger/queue.py) | Redis-backed work queue between the API and the outbound worker |
| [redis_client.py](../rag/messenger/redis_client.py) | Shared Redis connection factory |
| [schemas.py](../rag/messenger/schemas.py) | Pydantic schemas for inbound + outbound payloads |
| [payloads.py](../rag/messenger/payloads.py) | Payload builders for the Send API format |
| [routers/](../rag/messenger/routers/) | FastAPI routers mounted under `/webhook/messenger/*` |

n8n bridge workflow:
[automation/n8n/messenger-bridge.json](../automation/n8n/messenger-bridge.json).
nginx vhost: [infra/nginx/messenger.conf](../infra/nginx/messenger.conf).

## 8. Observability — Langfuse + OTel (v2 — Production)

[rag/observability/](../rag/observability/) inside the app:

| Module | Role |
|---|---|
| [tracing.py](../rag/observability/tracing.py) | OTel tracer setup + Langfuse client init |
| [decorators.py](../rag/observability/decorators.py) | `@traced(...)` decorator wrapping orchestrator nodes + retrieval stages |
| [diagnose.py](../rag/observability/diagnose.py) | Standalone diagnose CLI — verifies tracing pipeline end-to-end |

Backing services (docker):

- `langfuse-web` (Next.js UI, bound to `127.0.0.1:3100`).
- `langfuse-worker` (ingest pipeline → ClickHouse).
- `clickhouse` (trace + event store, healthcheck on `127.0.0.1:8123/ping`).
- `minio` (object store for large trace payloads, console on
  `127.0.0.1:9101`).
- OTel collector config: [otel/otel-collector-config.yaml](../otel/otel-collector-config.yaml)
  — the collector service stanza shipped in Phase 9.

No public Langfuse vhost yet; access via SSH tunnel.

## 9. Evaluation Harness

- Eval scripts directory: [rag/scripts/eval/](../rag/scripts/eval/)
  (scaffolding present, golden set + RAGAS runner not yet wired).
- Target golden set: `rag/data/eval/golden_qa.jsonl` (50+ Q/A pairs
  drawn from real vault notes; not yet seeded).
- Planned metrics: RAGAS Context Precision, Context Recall,
  Faithfulness, Answer Relevance, plus Context Entities Recall once
  GraphRAG measurement lands.
- CI gate (`.github/workflows/rag-eval.yml`) blocking PRs that
  regress Precision/Recall by > 5%: **not yet wired**.

## 10. Auth — JWT + Password + API Tokens

- [rag/routers/auth.py](../rag/routers/auth.py) — login (`POST
  /api/auth/login` returns JWT), JWT validation dependency.
- [rag/auth_overlay.py](../rag/auth_overlay.py) — global FastAPI
  middleware that 401s any unauthenticated `/api/*` request.
- [rag/routers/api_tokens.py](../rag/routers/api_tokens.py) — opaque
  bearer tokens with scopes (`chat:read`, `chat:write`,
  `documents:read`, `documents:write`, `dashboard:read`); shown once
  at creation, prefix stored for display.
- JWT secret in env (`JWT_SECRET`); rotation endpoint
  (`POST /api/settings/rotate-jwt`) invalidates all sessions.

## 11. SPA — Static Frontend

[rag/static/](../rag/static/) — hand-rolled vanilla-JS SPA served by
the same FastAPI app.

- `app.js` — single-file SPA, hash router, all page renderers,
  SSE chat client (streams `status` → `sources` → `token` →
  `followups` → `done` events).
- `index.html`, `style.css`, `widget.html` — shell + embeddable
  widget surface.

Pages: dashboard, documents, chat, conversations, logs, integrations,
resources, settings, changelog.

Chat now streams over the v2 LangGraph orchestrator
(`POST /api/chat/stream`) — the SSE event shape is unchanged, so no
SPA work was required for the Phase 9 cutover.

## 12. Integrations Outbound

- [rag/routers/integrations.py](../rag/routers/integrations.py) — CRUD
  for integration registrations + `POST /api/integrations/{id}/test`.
- [rag/integrations/](../rag/integrations/) — dispatcher modules per
  integration type.
- Users define a webhook URL + JSON config + subscribed event set
  (events advertised by `GET /api/integrations/events`). The dispatcher
  fires on subscribed events with `last_fired_at` + `last_status`
  surfaced in the SPA card.

## 13. Resources / Prompt Library

- [rag/routers/resources.py](../rag/routers/resources.py) — CRUD for
  prompt slugs; activate / deactivate; seed defaults.
- [rag/resources_store.py](../rag/resources_store.py) — storage layer
  for prompt bodies.
- Exactly one prompt may be `active` at a time; the orchestrator
  resolves its system prompt at runtime from this store.

## 14. Settings + Changelog + Logs surfaces

- [rag/routers/settings.py](../rag/routers/settings.py) +
  [rag/settings_service.py](../rag/settings_service.py) — tunable env
  settings with a JSON schema; read-only env block; password change;
  JWT rotate.
- [rag/routers/changelog.py](../rag/routers/changelog.py) — versioned
  changelog with unread-count badge on the SPA nav (`GET
  /api/changelog/unread`, `POST /api/changelog/mark-read`).
- [rag/routers/logs.py](../rag/routers/logs.py) — recent log entries
  surfaced to the SPA Logs page.

## 15. Deployment Infrastructure

### Surfaces

| Surface | Hostname | Routed to | Notes |
|---|---|---|---|
| RAG SPA + Chat | `chat.nexus.gayo-sphere.cloud` | nginx → `127.0.0.1:8210` → docker `api` container `:8000` | **Phase 9:** flipped from v1 systemd `:8501` → v2 docker stack |
| Messenger webhook | `messenger.nexus.gayo-sphere.cloud` | nginx → `127.0.0.1:8210` → docker `api` `:8000` | Same `api` container, separate vhost ([infra/nginx/messenger.conf](../infra/nginx/messenger.conf)) |
| Published vault | `nexus.gayo-sphere.cloud` | Quartz static from `_publish/`, deployed via [deploy-nexus.sh](../deploy-nexus.sh) | Unchanged by Phase 9 |
| Qdrant (Mac dev) | `qdrant.nexus.gayo-sphere.cloud:443` | standalone container `qdrant-nexus` `:6333` on host loopback | VPS itself talks to `http://qdrant:6333` over the docker `nexus_net` alias |
| Langfuse UI | `127.0.0.1:3100` (host loopback only) | docker `langfuse-web` `:3000` | No public vhost; SSH tunnel for access |

### VPS Details (Phase 9 state)

- **`nexus-chat.service` (v1 systemd unit on `:8501`)** — stopped +
  disabled (`systemctl disable --now nexus-chat`). Unit file
  preserved on disk for emergency rollback; the binary path it
  referenced (`/root/.local/bin/uv run uvicorn app:app --host
  127.0.0.1 --port 8501`) is intact.
- **`chat.nexus.gayo-sphere.cloud` nginx vhost** — `proxy_pass`
  retargeted from `http://127.0.0.1:8501` → `http://127.0.0.1:8210`.
  All SPA + chat traffic now lands in the docker `api` container.
- **docker-compose stack** — production overlay:
  ```
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
                 --env-file .env.prod up -d --build
  ```
  Services running: `api`, `outbound_worker`, `postgres`, `redis`,
  `litellm`, `clickhouse`, `minio`, `langfuse-web`, `langfuse-worker`.
  Compose-managed `qdrant` service disabled via the `external-qdrant`
  profile in [docker-compose.prod.yml](../docker-compose.prod.yml).
  Standalone `qdrant-nexus` container attached to `nexus_net` with
  alias `qdrant`.
- **Vault bind-mount** — `/home/nexus-vault:/vault:ro` on both `api`
  and `outbound_worker`.
- **Edge rate-limit zone** — `nexus_edge: 30r/s` defined in
  `/etc/nginx/conf.d/ratelimit.conf`; referenced by the messenger
  vhost (and now optionally by the flipped chat vhost).
- **Resource caps** — `api` 2 CPU / 4 G, `outbound_worker` 1 CPU /
  1 G, `litellm` 1 CPU / 1.5 G, `postgres` 1.5 CPU / 2 G, `redis` 1
  CPU / 768 M, `clickhouse` 2 CPU / 3 G, `langfuse-web` /
  `langfuse-worker` 1 CPU / 1 G each. See
  [docker-compose.prod.yml](../docker-compose.prod.yml).

### Deployment scripts

| Script | Purpose |
|---|---|
| [deploy-rag.sh](../deploy-rag.sh) | rsyncs vault + code to the VPS, runs `docker compose ... up -d --build`, ingests `--changed` |
| [deploy-nexus.sh](../deploy-nexus.sh) | Quartz publish — builds `_publish/public/` and rsyncs to the nginx root for `nexus.gayo-sphere.cloud` |

### Required env (`/home/nexus-rag/.env.prod`, on-host only)

`WEBHOOK_API_KEY`, `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`,
`LITELLM_SALT_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` (per litellm config), `LANGFUSE_SALT`,
`LANGFUSE_ENCRYPTION_KEY`, `LANGFUSE_NEXTAUTH_SECRET`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `OUTBOUND_DISPATCH_ENABLED`,
`MAKE_WEBHOOK_URL`, `QDRANT_URL=http://qdrant:6333`,
`QDRANT_API_KEY`, `JWT_SECRET`, `NEXUS_PASSWORD`,
`VAULT_PATH=/vault`, `GROQ_MODEL=llama-3.3-70b-versatile`,
`FOLLOWUP_MODEL=llama-3.1-8b-instant`,
`EMBED_MODEL=BAAI/bge-small-en-v1.5`.

---

## Shipped vs Built vs Missing — Matrix

| Capability | v1 (legacy) | v2 (now) |
|---|---|---|
| Linear ingest→retrieve→generate chain | ❌ Decommissioned | — |
| `rag.chat` SSE endpoint (direct Groq) | ❌ Decommissioned (legacy code in tree) | — |
| systemd `nexus-chat.service` on `:8501` | ❌ Decommissioned (disabled 2026-05-19) | — |
| `rag.ingest` + `rag.watcher` watchdog | ❌ Decommissioned (legacy code in tree) | — |
| Qdrant collection `nexus-vault` | ❌ Decommissioned (collection retained for archaeology) | — |
| Docker compose production stack | — | ✅ Production |
| LangGraph orchestrator ([rag/orchestrator/](../rag/orchestrator/)) | — | ✅ Production |
| LiteLLM gateway ([litellm/config.yaml](../litellm/config.yaml)) | — | ✅ Production |
| Langfuse + ClickHouse + MinIO observability | — | ✅ Production |
| OTel tracing decorators ([rag/observability/](../rag/observability/)) | — | ✅ Production |
| v2 ingestion ([rag/ingest_v2/](../rag/ingest_v2/)) + semantic + late chunking | — | ✅ Production |
| Qdrant collection `nexus-vault-v2` | — | ✅ Production |
| Hybrid retrieval (BM25 + dense) + RRF + cross-encoder rerank | — | ✅ Production |
| Wikilink graph one-hop expansion (`rag/data/nexus_graph.db`) | — | ✅ Production |
| Messenger surface (`messenger.nexus.gayo-sphere.cloud`) | — | ✅ Production |
| Guardrails — groundedness, entropy, validators, handover | — | ✅ Production |
| n8n bridge workflow + HMAC at the bridge | — | ✅ Production |
| OTel collector service stanza | — | ✅ Production (shipped Phase 9) |
| RAGAS eval CI gate (golden set + PR diff comment) | — | ❌ Not started |
| **v1 → v2 cutover (Phase 9)** | ✅ **Complete (2026-05-19)** | — |

---

> "The vault is the source of truth. The RAG layer is the cortex.
> The agent is the will. Keep all three honest."
