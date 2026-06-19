# NEXUS - All Context

Last updated: 2026-06-19 (vibecode-pro-max-kit harness upgraded v2.2.0 → v3.1.0; planning-example PRDs relocated into vc-generate-plan skill, intent-clarification/parallel-fan-out protocol docs removed by kit, backup-path refs reconciled)

This file is the root context entrypoint for the repo.

Use it for two things:

1. quick routing to the right context pack or root file
2. broad architecture and repository understanding

Start here before loading deeper context files.

---

## How This File Works (the `all-*.md` Convention)

Every `process/context/` directory has one `all-*.md` entrypoint that acts as an attachable quick router for that domain. This root file (`all-context.md`) is the top-level router. Context groups each have their own `all-{group}.md` entrypoint.

**The pattern:**

```
process/context/
  all-context.md                      <-- THIS FILE: root router
  planning/
    all-planning.md                   <-- group router for planning
  tests/
    all-tests.md                      <-- group router for tests
```

**How agents use it:**

1. Agent reads `all-context.md` first (this file)
2. Finds the relevant context group from the routing tables below
3. Reads that group's `all-{group}.md` entrypoint
4. Only then loads the specific deep doc needed

This layered routing keeps context windows small. Never load the whole `process/context/` tree.

---

## Project Identity & Operating Contract

**NEXUS** — a sovereign, enterprise-grade Retrieval-Augmented Generation system fused with an Obsidian Second Brain. **The vault is the source of truth; the RAG layer is the cortex.**

- **Owner:** Clarence Lloyd Gayo
- **Vault root:** `/Users/clarencelloydgayo/Gayo Sphere/Second Brain Nexus`
- **Published surface (Quartz v4):** https://nexus.gayo-sphere.cloud
- **RAG surface (FastAPI SPA + SSE chat):** https://chat.nexus.gayo-sphere.cloud

> **Operating contract note:** This repo previously ran a bespoke "THE BUILDER / Command Chain" contract in `CLAUDE.md` (User → Gemini Director → Antigravity Inspector → Builder). That full contract is preserved in git history (pre-v3.1.0; local gitignored copy at `.vibecode-backup-1781876376/CLAUDE.md`). The repo now runs the **RIPER-5** harness (CLAUDE.md = managed protocol). The enterprise-RAG technical reference that used to live in CLAUDE.md has been migrated into this file. When the two conflict on *workflow*, RIPER-5 governs; when they conflict on *RAG architecture targets*, this file governs.

---

## Current Root Entry Points

| File | Read when |
|---|---|
| `process/context/all-context.md` | any substantial planning, research, review, or implementation task |
| `process/context/tests/all-tests.md` | testing, verification, debugging test failures, execution planning |
| `process/context/planning/all-planning.md` | plan-shape calibration (SIMPLE vs COMPLEX); formats owned by the `vc-generate-plan` skill |

## Current Context Groups

| Group | Entry point | Scope |
|---|---|---|
| `planning/` | `process/context/planning/all-planning.md` | plan-shape calibration; SIMPLE/COMPLEX example PRDs relocated to `.claude/skills/vc-generate-plan/references/` in kit v3.1.0 |
| `tests/` | `process/context/tests/all-tests.md` | pytest runners, commands, markers, ruff/mypy gates, debugging, gaps |

> Future groups to create as they reach the 3-doc / 800-line threshold: `rag-pipeline/` (the 5-stage retrieval spec), `messenger/` (Meta webhook + HITL), `infra/` (VPS, systemd, nginx, Qdrant, deploy), `auth/` (fastapi-users IAM).

## Task Routing Table

| If the task involves... | Start with | Then load |
|---|---|---|
| architecture or stack questions | this file | — |
| RAG pipeline (ingest/retrieve/rerank/generate) | this file → "RAG Pipeline" section | the relevant `rag/` module |
| testing or verification | this file, `tests/all-tests.md` | the specific test dir |
| creating a new plan | this file, `planning/all-planning.md` | `vc-generate-plan` skill (SIMPLE/COMPLEX format) |
| messenger / Meta webhook / HITL | this file → "Subsystems" | `rag/messenger/` |
| deploy / VPS / systemd / Qdrant | this file → "Deploy & Ops" | `deploy-rag.sh`, `deploy-nexus.sh` |

---

## Repository Structure

```
Second Brain Nexus/                  (Obsidian PARA vault + RAG system)
  00 - Inbox/ … 07 - Entities/       PARA buckets (vault source of truth)
  05 - Daily Notes/  Dev Logs/        journal + engineering logs
  rag/                                <-- PRIMARY: Python RAG system (uv, FastAPI)
    app.py main.py chat.py query.py   app entrypoints + chat/query surface
    ingest.py watcher.py              v1 ingestion + watchdog file observer
    config.py settings_service.py     config + runtime settings
    auth/                             fastapi-users IAM (Phase 27)
    database/ migrations/             SQLAlchemy + Alembic (Postgres)
    retrieval/                        dense retrieval + cross-encoder rerank
    ingest_v2/                        layout-aware ingest, graph_db wikilinks
    orchestrator/                     LangGraph-style nodes, llm, sales_tools
    guardrails/                       validators + pipeline (input/output safety)
    messenger/                        Meta Messenger webhook, sender, triage, HITL
    products/ resources_store.py      product catalog + resources
    routers/ services/                FastAPI routers + service layer
    observability/                    OTel spans, trace store
    integrations/                     external wiring
    static/ widget-static/            chat SPA + embeddable widget
    scripts/                          ops + backfill + (planned) eval harness
    tests/ + <pkg>/tests/             96 test files across 7 dirs
  _publish/                           Quartz v4 (Node ≥22) → nexus.gayo-sphere.cloud
  automation/ infra/ litellm/ otel/   orchestration, infra-as-code, model proxy, telemetry
  nexus-ui/ scripts/ docs/            UI assets, ops scripts, docs
  process/                            RIPER-5 harness (this context system)
  deploy-rag.sh  deploy-nexus.sh      production deploy scripts
```

## Technology Stack

**Core RAG (`rag/`, the primary package — `rag/pyproject.toml`, name `nexus-rag`):**

- **Language/runtime:** Python ≥3.11 (venv on 3.13), managed by **uv** (`uv sync`, `uv run`).
- **API:** FastAPI ≥0.115 + Uvicorn (standard). Auth-gated SPA + **SSE** streaming chat.
- **Vector store:** **Qdrant** (`qdrant-client[fastembed]` ≥1.14), collection `nexus-vault`, 384-dim cosine.
- **Embeddings:** **`BAAI/bge-small-en-v1.5`** via fastembed (pinned `fastembed>=0.4,<1.0`). NOTE: on disk this resolves to `models--qdrant--bge-small-en-v1.5-onnx-q` — never predict the cache path from the user-facing ID.
- **Reranker:** fastembed `TextCrossEncoder` (see `rag/retrieval/rerank.py`; the `fastembed` pin guards against a qdrant-client bump dropping/relocating it).
- **LLM:** **Groq** — primary `llama-3.3-70b-versatile` (temp 0.3, max 1024); follow-ups `llama-3.1-8b-instant` (temp 0.5, 3 per turn).
- **Relational/IAM:** SQLAlchemy 2 (asyncio) + **asyncpg** (Postgres) + **Alembic**; `fastapi-users[sqlalchemy]` (Phase 27).
- **Object storage:** `aioboto3` + Pillow — MinIO-backed avatar uploads (Phase 28).
- **Retrieval arms (`rag/retrieval/`):** `dense.py` (Qdrant cosine), `sparse.py` (BM25 via `rank_bm25`, in-mem cache `BM25_CACHE_TTL_SECONDS=3600`), `rrf.py` (`reciprocal_rank_fusion`, `DEFAULT_K=60`), `graph.py` (Phase 31 Postgres-backed one-hop wikilink walk on `app.document_links`, tenant-scoped), `rerank.py` (fastembed `TextCrossEncoder`).
- **Graph/wikilinks:** Phase 31 moved graph retrieval to **Postgres** (`app.document_links`, tenant-scoped) — see `rag/retrieval/graph.py`. The legacy on-disk SQLite `rag/data/nexus_graph.db` (`rag/ingest_v2/graph_db.py`) is being retired; `aiosqlite` stays pinned only for the ingest-side resolver until that lands.
- **Tokenizer:** `tiktoken` (cl100k). **PDF:** `pypdf` + `pymupdf`. **Frontmatter:** `python-frontmatter`. **Watcher:** `watchdog`.
- **Auth tokens:** `python-jose[cryptography]`, `python-multipart`.

**Publishing (`_publish/`):** Quartz **v4.5.2** (Node ≥22, ESM, TypeScript) → static site.

**Dev tooling:** pytest (+asyncio, +cov), **ruff** (check+format), **mypy --strict** (scoped to new modules), fakeredis, moto (S3).

## RAG Pipeline — Target Architecture (5 stages)

Migrated from the old CLAUDE.md. Every PR in `rag/` should close a gap or harden a stage.

1. **Ingestion** — layout-aware Markdown splitting (heading-path tree), semantic-boundary detection (`SEMANTIC_BREAK_THRESHOLD=0.55`), token envelope `CHUNK_TOKENS=400`/`CHUNK_OVERLAP=50` (tiktoken cl100k), code-fence preservation, frontmatter-as-metadata.
2. **Metadata extraction** — rich per-chunk payload (file, folder/PARA, title, heading_path, tags, aliases, wikilinks in/out, dates, content_hash, chunk_index/total, source_kind, language). Log `metadata.gap` on missing fields.
3. **Hybrid retrieval** — BM25 (sparse) + bge-small dense, fused with **RRF** (`k=60`), `RETRIEVE_K=50` per arm; filters honored at retrieval time.
4. **Cross-encoder rerank** — `ms-marco-MiniLM-L-6-v2` (or BGE reranker), top-50 → `TOP_K=6`; optional recency bias (λ default 0.0); log bm25/dense/rrf/rerank scores.
5. **Generation** — Groq streaming with strict `[n]` citation enforcement; SSE event order `status → sources → token×N → followups → done`.

**Implementation status (verified against code at HEAD 3c4d7f2, 2026-05-31):**
- Ingestion: header walk + 400/50 chunking shipped; semantic-boundary detector + code-fence preservation still gaps.
- Metadata: partial (file, folder, title, heading, tags, content_hash); wikilinks/aliases/source_kind/language partial.
- **Retrieval: HYBRID shipped** — dense (Qdrant) + sparse (BM25) + RRF fusion (`k=60`) + Phase 31 Postgres graph arm. This is **past** the old "pure dense" baseline.
- Rerank: shipped (fastembed `TextCrossEncoder`).
- Generation: shipped (Groq streaming + `[n]` citations + follow-ups).
- Observability/evals: trace store partial; RAGAS harness still to build.

> The old CLAUDE.md "as of 2026-05-14" baseline is superseded — phases 27–39 shipped IAM, MinIO, hybrid+graph retrieval, messenger/HITL, sales tools, sentiment, Seina persona, and SaaS showcase. Always confirm against `rag/` before quoting.

## Subsystems (recent phase work, from CHANGELOG / Dev Logs)

- **Messenger (`rag/messenger/`):** Meta Messenger webhook, Graph-API sender, **triage**, **HITL** handover (Phase 37 — owner notification + pause), comment dispatch. Modules: `hitl.py`, `triage.py`.
- **Sales/SDR (`rag/orchestrator/sales_tools.py`):** `generate_checkout_link()` / `capture_lead()` POST to n8n webhooks (Stripe + GoHighLevel CRM) — Phase 34.
- **Seina persona (`rag/orchestrator/prompts/system_brix.md`):** Phase 38.x — Messenger system prompt rewritten; persona named "Seina"; product-recall pronoun rules; greeting/CRM/transactional-grace guidance. `product_branch.py` dedup gate expanded to last-3 assistant messages.
- **Sentiment / Cognitive Empathy (Phase 35):** sentiment node + dynamic prompt routing.
- **Product context (Phase 32.x):** catalog rows hoisted into LLM context, carousel image URLs Meta-fetchable, payload normalization/backfill.
- **Guardrails (`rag/guardrails/`):** input/output validators + pipeline.
- **SaaS showcase (`nexus-ui/`, Phase 39):** `/whats-new` curated capability page (4 active + 4 locked roadmap cards). Premium integration empty states: `PremiumIntegrationsGrid` + `IntegrationCard` + `PremiumConnectModal` mounted in `IntegrationsPage`. `GET /api/integrations/catalog` read-only stub endpoint (Hunter + Akiro, enterprise tier, no DB/env).
- **Workspace Manager (Phases 50–53, SHIPPED 2026-06-12):** full B2B workspace management. 3-tier RBAC `owner|admin|member` (`require_manager` in `rag/routers/deps.py`, CHECK constraint migration 0008); member CRUD + token-based invites (`rag/routers/tenant_invites.py`, SHA-256 token_hash, n8n email webhook, public `/api/invites/accept`, `/join` route); lifecycle (migration 0010 `avatar_url`/`archived_at`, PATCH rename/slug — slug blocked while documents exist, MinIO tenant avatars, archive guard in `get_current_tenant` with `/api/tenants` exemption, ownership transfer, hard-delete: Qdrant slug-filter cascade then Postgres FK cascade); usage telemetry (`GET /api/tenants/{id}/usage` — doc/product/member counts, Qdrant chunk count with graceful null degrade, 7-day message buckets). UI: master-detail `/settings/workspaces/:slug` with General/Members/Usage/Advanced Radix tabs.

## Key Patterns and Conventions

- **Async-first.** All network I/O (Qdrant, Groq, Obsidian writes, Postgres) is async; never block the event loop. SQLite via `aiosqlite`.
- **Secrets in env, never in code.** `python-dotenv` locally; systemd `EnvironmentFile` on the VPS. Never echo secrets to logs.
- **Errors propagate.** No silent `except:`. Catch only what you can recover; log and re-raise the rest.
- **Tests next to code.** Each subpackage owns a `tests/` dir; root suite in `rag/tests/`. `asyncio_mode = auto`, markers `unit` / `integration`.
- **mypy strict is opt-in per module** — only modules listed under `[tool.mypy].files` are held to `--strict`. Add a module there only after it is strict-clean.
- **Phase-stamped work.** Changes are tracked as "Phase NN.x" in `CHANGELOG.md` + `Dev Logs/`.
- **`pythonpath = [".."]`** so `from rag.X import Y` resolves the same way the container does (`PYTHONPATH=/app`).
- **No ingestion bypass paths.** Every ingestion source routes through the same metadata-extraction pass as `ingest.py`.

## Environment and Configuration

**Config files:** `rag/pyproject.toml` (project + pytest + ruff + mypy), `rag/uv.lock`, `rag/.env` (gitignored, Mac dev), `/home/nexus-rag/.env` (VPS prod, edited in place, preserved across deploys), `_publish/package.json`.

**Env var groups (names only, never values):**
- **LLM:** `GROQ_API_KEY`, `GROQ_MODEL` (`llama-3.3-70b-versatile`), `FOLLOWUP_MODEL` (`llama-3.1-8b-instant`)
- **Vector:** `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` (`nexus-vault`), `EMBED_MODEL` (`BAAI/bge-small-en-v1.5`)
- **Auth:** `JWT_SECRET` (≥32 bytes), `NEXUS_PASSWORD`
- **Vault:** `VAULT_PATH`
- **Messenger / HITL (Phase 37):** `MESSENGER_APP_ID`, `HITL_PAUSE_DURATION_S` (default 3600)
- **n8n SDR webhooks (Phase 34/37):** `N8N_WEBHOOK_CHECKOUT_URL`, `N8N_WEBHOOK_LEAD_URL`, `N8N_WEBHOOK_NOTIFY_URL`

**Mac dev vs VPS prod differ on:** `QDRANT_URL` (Mac `https://qdrant.nexus.gayo-sphere.cloud:443` / VPS `http://127.0.0.1:6333`) and `VAULT_PATH` (Mac local disk / VPS `/home/nexus-vault`).

## Deploy & Ops

- **RAG deploy:** `./deploy-rag.sh` — **Docker Compose v2 architecture** (the legacy `nexus-chat` systemd unit + `/home/nexus-rag` tree are DECOMMISSIONED). rsyncs vault → `/home/nexus-vault`, `rag/` + `nexus-ui/` + infra → `/home/nexus-rag-v2`, rebuilds the **`nexus-api`** container (`docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build api`), waits healthy, then runs `docker exec -w /app/rag nexus-api alembic upgrade head`. **Env lives in `/home/nexus-rag-v2/.env.prod`** (NOT `/home/nexus-rag/.env`) — set runtime flags there and **recreate** the container (`--force-recreate`; a restart does NOT reload `--env-file`). `.env`/`.env.prod` preserved (rsync excludes). nginx proxies (CloudPanel + Let's Encrypt).
- **Quartz publish:** `./deploy-nexus.sh` — `nvm use 22` then rsync built `_publish/public/` → https://nexus.gayo-sphere.cloud.
- **Qdrant:** Docker container `qdrant-nexus` on VPS `72.62.196.231`, port 6333, data `/home/nexus-qdrant/storage/`. Public HTTPS `https://qdrant.nexus.gayo-sphere.cloud:443` (Mac path); VPS talks to `127.0.0.1:6333` directly.
- **Post-deploy verify:** `curl -sSI https://chat.nexus.gayo-sphere.cloud/` → 200; `docker inspect --format '{{.State.Health.Status}}' nexus-api` → healthy; `docker logs nexus-api --tail 50`; current migration `docker exec -w /app/rag nexus-api alembic current`.
- **MCP servers in play:** Playwright (E2E), `gayo-vps` SSH (deploy/logs), `wordpress-cms`.

## Current Features

Feature folders with 5+ artifacts or multi-phase programs. Stored under `process/features/{feature}/`.

| Feature | Status | Notes |
|---|---|---|
| `tenant-ai-customization` | ✅ SHIPPED (2026-06-04) | Phases 45–49 ALL shipped: Lifecycle Persona Engine, Knowledge Boundary Harden, Workflow Toggles, Model Params, Prompt Studio frontend + GET/PUT /workspace/ai-settings |
| `workspace-manager` | ✅ SHIPPED (2026-06-12) | Phases 50–53 ALL shipped: 3-tier RBAC (owner/admin/member), token-based invites + n8n emails + `/join` flow, workspace lifecycle (rename/slug/avatar, archive, ownership transfer, hard-delete with Qdrant cascade), usage telemetry dashboard. Plan archived at `process/features/workspace-manager/completed/` |
| `nexus-flow` | ✅ V1 EPIC COMPLETE — 58.1+58.2+58.3 SHIPPED + DEPLOYED + MERGED (2026-06-19) | Visual node-based FB automation builder (supersedes Phase 57 keyword engine, coexists-w-precedence via `nexus_flows_enabled`). PR **#3 MERGED → main** (`a4f5ea3`); branch deleted. 58.1: migration 0015 (`nexus_flows` + `flow_runs`), stateful JSON-graph engine (`rag/messenger/flow_engine.py`) w/ Wait-for-Input resume, CRUD API, React Flow (`@xyflow/react`) canvas `/flows`. 58.2: AI Intent Router (`chat_complete` classify → dynamic intent handles, strict `other` fallback) + Pause (`set_bot_paused` 24h, terminal) + reusable Node Inspector (`useReactFlow().setNodes`). 58.3: Trigger Webhook (best-effort templated `httpx` POST) + Update CRM (migration 0016 `flow_contacts`; tag/field/hot_lead upsert). **V1 = 9 nodes + Inspector.** All plans archived to `completed/`. **V2 fast-follows:** 🔴 Webhook SSRF egress hardening (top gate — tenant-controlled URL → internal services), 58.4 Instagram Story Mention + flow analytics, CRM-read/condition-on-tags. |

## Context Group Lifecycle

Context groups are durable knowledge domains, not feature folders. Create a group when a topic has 3+ durable docs, or a single doc exceeds ~800 lines with separable subtopics. Do not create a group for temporary reports, plans, or feature-specific content (those live in `process/features/...`). Run the `vc-audit-context` skill after any context reorganization.

## Naming Convention

No `README.md` inside `process/context/`. Canonical entrypoints use `all-*.md` (root: `all-context.md`; group: `{group}/all-{group}.md`).

## Context Update Protocol

When durable project knowledge changes: (1) update the smallest relevant context file; (2) update this file if routing/ownership/naming/groups changed; (3) update the owning `all-{group}.md`; (4) run `vc-audit-context`.

---

## Source References

This context was mined from, and should be reconciled against, these in-repo sources:

- git history (pre-v3.1.0; local gitignored copy at `.vibecode-backup-1781876376/CLAUDE.md`) — the original NEXUS "THE BUILDER" contract + full 5-stage RAG technical reference (primary source for this file).
- `rag/pyproject.toml` — authoritative stack, dependency pins, pytest/ruff/mypy config.
- `CHANGELOG.md` — Keep-a-Changelog history; phase-by-phase user-visible changes.
- `Dev Logs/` — engineering work logs (`YYYY-MM-DD — <Title>.md`).
- `_publish/package.json` — Quartz publishing toolchain.
- `deploy-rag.sh`, `deploy-nexus.sh` — production deploy procedures.
- `rag/<subpackage>/` source — the truth when this file and code disagree; verify before quoting pipeline state.

## Open Questions / Outstanding Work

Real remaining gaps (verified against code at HEAD 3c4d7f2 — hybrid retrieval and graph arm are NOT gaps, they shipped):

- **Ingestion** — semantic-boundary detector and code-fence preservation not yet implemented (Stage 1 gap).
- **Metadata** — wikilinks index, aliases, `source_kind`, `language` only partially populated (Stage 2 gap).
- **BM25 persistence** — sparse arm is shipped but in-memory only; `sparse.py` notes "Phase 4 will swap this for a persisted `rank_bm25` snapshot." Until then BM25 rebuilds per-process.
- **Graph DB migration tail** — graph *retrieval* is Postgres now (Phase 31); the legacy SQLite `rag/data/nexus_graph.db` ingest-side resolver still exists, keeping the `aiosqlite` pin alive until it's folded in.
- **Evals** — no RAGAS harness, golden set, or CI regression gate yet (`rag/scripts/eval/` planned).
- **Observability** — append-only JSONL trace store + OTel spans only partially in place.
- **Operating-contract reconciliation** — RESOLVED 2026-05-31: RIPER-5 (CLAUDE.md) is the chosen live workflow; the legacy "THE BUILDER / Command Chain" contract is archived in git history (pre-v3.1.0; local gitignored copy at `.vibecode-backup-1781876376/CLAUDE.md`) for reference only.

---

## Scan Metadata

- Generated: 2026-05-31 (vc-setup STUDY phase)
- HEAD: 3c4d7f2
- Mode: existing project, fresh `process/` scaffold (context mined from git history (pre-v3.1.0; local gitignored copy at `.vibecode-backup-1781876376/CLAUDE.md`) + codebase scan)
- Primary package manager: **uv** (Python, `rag/`); secondary **npm** (Node ≥22, `_publish/`)
- Real project test files: 96 (across 7 `tests/` dirs under `rag/`)
