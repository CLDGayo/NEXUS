# NEXUS - All Context

Last updated: 2026-05-31 (STUDY phase, HEAD 3c4d7f2)

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
    example-simple-prd.md
    example-complex-prd.md
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

> **Operating contract note:** This repo previously ran a bespoke "THE BUILDER / Command Chain" contract in `CLAUDE.md` (User → Gemini Director → Antigravity Inspector → Builder). That full contract is preserved at `.vibecode-backup/CLAUDE.md`. The repo now runs the **RIPER-5** harness (CLAUDE.md = managed protocol). The enterprise-RAG technical reference that used to live in CLAUDE.md has been migrated into this file. When the two conflict on *workflow*, RIPER-5 governs; when they conflict on *RAG architecture targets*, this file governs.

---

## Current Root Entry Points

| File | Read when |
|---|---|
| `process/context/all-context.md` | any substantial planning, research, review, or implementation task |
| `process/context/tests/all-tests.md` | testing, verification, debugging test failures, execution planning |
| `process/context/planning/all-planning.md` | plan-shape calibration, SIMPLE vs COMPLEX reference docs |

## Current Context Groups

| Group | Entry point | Scope |
|---|---|---|
| `planning/` | `process/context/planning/all-planning.md` | plan-shape calibration, SIMPLE vs COMPLEX PRD examples |
| `tests/` | `process/context/tests/all-tests.md` | pytest runners, commands, markers, ruff/mypy gates, debugging, gaps |

> Future groups to create as they reach the 3-doc / 800-line threshold: `rag-pipeline/` (the 5-stage retrieval spec), `messenger/` (Meta webhook + HITL), `infra/` (VPS, systemd, nginx, Qdrant, deploy), `auth/` (fastapi-users IAM).

## Task Routing Table

| If the task involves... | Start with | Then load |
|---|---|---|
| architecture or stack questions | this file | — |
| RAG pipeline (ingest/retrieve/rerank/generate) | this file → "RAG Pipeline" section | the relevant `rag/` module |
| testing or verification | this file, `tests/all-tests.md` | the specific test dir |
| creating a new plan | this file, `planning/all-planning.md` | SIMPLE/COMPLEX PRD example |
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
- **Graph/wikilinks:** on-disk SQLite at `rag/data/nexus_graph.db` via `rag/ingest_v2/graph_db.py` (`aiosqlite`; planned fold into Postgres).
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

**Implementation baseline (per old CLAUDE.md, as of 2026-05-14):** ingestion = header walk + 400/50 (no semantic detector/fence preservation yet); metadata = partial; retrieval = **pure dense** (BM25+RRF missing); rerank = present via fastembed; generation = shipped (Groq streaming + citations + follow-ups); observability/evals = trace store + RAGAS still to build. **Verify current state against code before quoting — phases 27–37 have shipped since.**

## Subsystems (recent phase work, from CHANGELOG / Dev Logs)

- **Messenger (`rag/messenger/`):** Meta Messenger webhook, Graph-API sender, **triage**, **HITL** handover (Phase 37 — owner notification + pause), comment dispatch. New since last commit: `hitl.py`, `triage.py` + tests.
- **Sales/SDR (`rag/orchestrator/sales_tools.py`):** `generate_checkout_link()` / `capture_lead()` POST to n8n webhooks (Stripe + GoHighLevel CRM) — Phase 34.
- **Sentiment / Cognitive Empathy (Phase 35):** sentiment node + dynamic prompt routing.
- **Product context (Phase 32.x):** catalog rows hoisted into LLM context, carousel image URLs Meta-fetchable, payload normalization/backfill.
- **Guardrails (`rag/guardrails/`):** input/output validators + pipeline.

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

- **RAG deploy:** `./deploy-rag.sh` — rsync vault+code, full reindex, restart `nexus-chat` systemd unit → https://chat.nexus.gayo-sphere.cloud. Unit `ExecStart=uv run uvicorn app:app --host 127.0.0.1 --port 8501`, `EnvironmentFile=/home/nexus-rag/.env`, `Restart=always`. nginx proxies (CloudPanel + Let's Encrypt). `.env` preserved (`rsync --exclude='.env'`).
- **Quartz publish:** `./deploy-nexus.sh` — `nvm use 22` then rsync built `_publish/public/` → https://nexus.gayo-sphere.cloud.
- **Qdrant:** Docker container `qdrant-nexus` on VPS `72.62.196.231`, port 6333, data `/home/nexus-qdrant/storage/`. Public HTTPS `https://qdrant.nexus.gayo-sphere.cloud:443` (Mac path); VPS talks to `127.0.0.1:6333` directly.
- **Post-deploy verify:** `curl -sSI https://chat.nexus.gayo-sphere.cloud/` → 200; `systemctl is-active nexus-chat` → active; `journalctl -u nexus-chat -n 50`.
- **MCP servers in play:** Playwright (E2E), `gayo-vps` SSH (deploy/logs), `wordpress-cms`.

## Context Group Lifecycle

Context groups are durable knowledge domains, not feature folders. Create a group when a topic has 3+ durable docs, or a single doc exceeds ~800 lines with separable subtopics. Do not create a group for temporary reports, plans, or feature-specific content (those live in `process/features/...`). Run the `vc-audit-context` skill after any context reorganization.

## Naming Convention

No `README.md` inside `process/context/`. Canonical entrypoints use `all-*.md` (root: `all-context.md`; group: `{group}/all-{group}.md`).

## Context Update Protocol

When durable project knowledge changes: (1) update the smallest relevant context file; (2) update this file if routing/ownership/naming/groups changed; (3) update the owning `all-{group}.md`; (4) run `vc-audit-context`.

---

## Source References

This context was mined from, and should be reconciled against, these in-repo sources:

- `.vibecode-backup/CLAUDE.md` — the original NEXUS "THE BUILDER" contract + full 5-stage RAG technical reference (primary source for this file).
- `rag/pyproject.toml` — authoritative stack, dependency pins, pytest/ruff/mypy config.
- `CHANGELOG.md` — Keep-a-Changelog history; phase-by-phase user-visible changes.
- `Dev Logs/` — engineering work logs (`YYYY-MM-DD — <Title>.md`).
- `_publish/package.json` — Quartz publishing toolchain.
- `deploy-rag.sh`, `deploy-nexus.sh` — production deploy procedures.
- `rag/<subpackage>/` source — the truth when this file and code disagree; verify before quoting pipeline state.

## Open Questions / Outstanding Work

Target-vs-shipped gaps (from the RAG pipeline spec — confirm against code before acting):

- **Hybrid retrieval incomplete** — BM25 sparse arm + RRF fusion not shipped; retrieval is pure dense. (Stage 3 gap.)
- **Ingestion** — semantic-boundary detector and code-fence preservation not yet implemented (Stage 1 gap).
- **Metadata** — wikilinks index, aliases, `source_kind`, `language` only partially populated (Stage 2 gap).
- **Evals** — no RAGAS harness, golden set, or CI regression gate yet (`rag/scripts/eval/` planned).
- **Observability** — append-only JSONL trace store + OTel spans only partially in place.
- **Graph DB** — `rag/data/nexus_graph.db` (SQLite) is slated to fold into Postgres; the `aiosqlite` pin drops when it does.
- **Operating-contract reconciliation** — RIPER-5 (CLAUDE.md) now coexists with the legacy "THE BUILDER / Command Chain" contract (`.vibecode-backup/CLAUDE.md`). Decide which governs the live workflow long-term.

---

## Scan Metadata

- Generated: 2026-05-31 (vc-setup STUDY phase)
- HEAD: 3c4d7f2
- Mode: existing project, fresh `process/` scaffold (context mined from `.vibecode-backup/CLAUDE.md` + codebase scan)
- Primary package manager: **uv** (Python, `rag/`); secondary **npm** (Node ≥22, `_publish/`)
- Real project test files: 96 (across 7 `tests/` dirs under `rag/`)
