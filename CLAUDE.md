# NEXUS — Enterprise RAG Second Brain

> **Repository identity.** Nexus is a sovereign, enterprise-grade Retrieval-Augmented Generation system fused with an Obsidian Second Brain. The vault is the source of truth; the RAG layer is the cortex. This file is your operating manual — read it before doing anything in this repo.

**Owner:** Clarence Lloyd Gayo
**Vault root:** `/Users/clarencelloydgayo/Gayo Sphere/Second Brain Nexus`
**Published surface:** https://nexus.gayo-sphere.cloud (Quartz v4)
**RAG surface:** FastAPI app under `rag/` (auth-gated SPA + SSE chat)

---

## 1. Enterprise RAG Architecture

Nexus implements a **five-stage retrieval pipeline**. Every stage is auditable, every artifact is observable, every score is logged. Treat this as the target architecture — when you write code in `rag/`, you are either shipping a stage or improving one.

### Stage 1 — Ingestion: Layout-Aware + Semantic Chunking

Markdown is not flat prose. Respect it.

- **Layout-aware splitting.** Parse each note into a tree of Markdown headings (`#`, `##`, `###`, `####`). Heading path travels with the chunk as `heading_path: ["Parent", "Child", "Leaf"]` so the LLM sees structural context.
- **Semantic boundaries inside leaves.** Within each leaf section, split paragraphs using a sliding-window cosine-similarity check on adjacent sentence embeddings; cut where similarity drops below a configured threshold (`SEMANTIC_BREAK_THRESHOLD`, default `0.55`). Prevents mid-thought splits that pure-token chunkers produce.
- **Token budget envelope.** Cap each chunk at `CHUNK_TOKENS=400` with `CHUNK_OVERLAP=50` measured by `tiktoken` cl100k. Overlap is taken from the previous semantically-coherent unit, not a blind tail.
- **Code-fence preservation.** Triple-backtick blocks are never split; if a fence exceeds the token budget, emit it as a single oversized chunk with `oversize: true` and a follow-up summary chunk.
- **Frontmatter is metadata, not content.** Parse YAML frontmatter, attach to every chunk, do **not** embed the YAML text itself.

### Stage 2 — Automated Metadata Extraction

Every chunk written to the vector store carries a rich, queryable payload. Extract at ingestion time, never at query time:

| Field | Source | Purpose |
|---|---|---|
| `file` | absolute path | citation, dedup, vector GC |
| `folder` | PARA bucket | filter by `Projects` / `Areas` / `Resources` / `Archive` |
| `title` | frontmatter or first `#` | display name |
| `heading_path` | layout walk | structural context |
| `tags` | frontmatter `tags:` + inline `#tag` | facet filters |
| `aliases` | frontmatter `aliases:` | query expansion |
| `wikilinks_out` | `[[…]]` parser | GraphRAG edges |
| `wikilinks_in` | reverse index | backlink boosting |
| `date_created` / `date_modified` | filesystem stat or frontmatter | recency reranking |
| `content_hash` | SHA-256 of body | idempotent re-ingest |
| `chunk_index` / `chunk_total` | layout walk | reassembly |
| `source_kind` | `note` / `daily` / `inbox-pdf` / `inbox-md` | source mixing |
| `language` | fasttext detect | route to multilingual model when needed |

If a field is missing, log a `metadata.gap` event — don't silently default.

### Stage 3 — Hybrid Retrieval (BM25 + Dense)

Pure-vector retrieval misses exact-name queries (people, projects, codes). Pure BM25 misses paraphrase. Run both and fuse.

- **Sparse arm — BM25.** Maintain a `rank_bm25` (or Tantivy) index built over the same chunk corpus. Tokenize with the same scheme used for the dense arm's tokenizer to keep BM25 comparable.
- **Dense arm — bge-small-en-v1.5.** 384-dim cosine in Qdrant collection `nexus-vault`. Query embedding uses the identical model used at ingestion (drift detection: fail if `EMBED_MODEL` env disagrees with collection metadata).
- **Fusion — Reciprocal Rank Fusion (RRF).** Combine sparse and dense rankings using `score = Σ 1 / (k + rank)` with `k=60`. Pull `RETRIEVE_K=50` candidates from each arm before fusion.
- **Filters at retrieval time.** Always honor folder / tag / date / `source_kind` filters from the query parser — cheap and dramatically improves precision.

### Stage 4 — Cross-Encoder Reranking

The top of the fused list is noisy. Pay the latency to reorder.

- **Model.** `cross-encoder/ms-marco-MiniLM-L-6-v2` (or BGE reranker for multilingual notes).
- **Input.** Take top-50 from RRF, score each `(query, chunk_text)` pair, sort by reranker score, return `TOP_K=6`.
- **Recency bias (optional).** Add `λ · recency_score` to reranker score when the query parser detects a temporal intent ("recent", "this week"). λ defaults to `0.0` — opt-in only.
- **Score logging.** Persist `bm25_rank`, `dense_rank`, `rrf_score`, `rerank_score` per surviving chunk in the trace store for evals.

### Stage 5 — Generation with Citation Enforcement

- **Primary model.** Groq `llama-3.3-70b-versatile`, temperature `0.3`, max tokens `1024`.
- **Follow-up model.** Groq `llama-3.1-8b-instant`, temperature `0.5` — three follow-ups per turn.
- **Strict citation format.** Sources injected as `Source [n]: <display_name>\nContent: ...`. The system prompt requires every factual claim to carry `[n]` citations and to refuse when the retrieved context cannot support the answer.
- **Streaming.** SSE events: `status` → `sources` → `token` (× N) → `followups` → `done`. Never buffer the full answer server-side.

### Current Implementation Baseline (as of 2026-05-14)

| Stage | Shipped | Gap |
|---|---|---|
| Ingestion: layout-aware | header walk + 400/50 chunking in `rag/ingest.py` | no semantic-boundary detector; no fence preservation |
| Metadata extraction | partial (file, folder, title, heading, tags, content_hash) | no wikilinks index, no aliases, no `source_kind`, no language |
| Hybrid retrieval | pure dense (Qdrant cosine) | BM25 arm + RRF fusion missing |
| Reranking | none | cross-encoder reranker missing |
| Generation | Groq streaming + citations + follow-ups | — |
| Observability / evals | no trace store, no RAGAS harness | build per §4 |

**Read this table before proposing changes.** Every PR should either close a gap or harden a shipped stage; do not add features outside the pipeline.

---

## 2. Core Skills & MCP Server Integrations

You are not a context-bound chatbot. You have a toolkit. Use it.

### Required MCP Servers

| MCP | Purpose | When to invoke |
|---|---|---|
| **Playwright MCP** (`playwright@claude-plugins-official`) | Browser automation | E2E testing the RAG SPA; verifying chat UI streams correctly |
| **VPS SSH MCP** (`gayo-vps`) | SSH into prod VPS (`72.62.196.231`) | Deploy commands, systemd service ops, log tailing, nginx config |
| **WordPress MCP** (`wordpress-cms`) | CMS ops for gayo-sphere.cloud | Post drafts, media uploads, plugin queries |
| ~~Filesystem MCP~~ | _Not configured_ | Install via settings.json when needed |
| ~~Qdrant MCP~~ | _Not configured_ | Install via settings.json when needed |
| ~~GitHub MCP~~ | _Not configured_ | Use `gh` CLI as fallback |
| ~~Context7 MCP~~ | _Not configured_ | Use web search as fallback |

When an MCP for a needed capability isn't present, **say so** and either propose the install or fall back to local tools with a logged degradation.

### Skills to Engage Proactively

| Skill | Trigger |
|---|---|
| `obsidian-second-brain` | Any vault read/write, daily notes, kanban, person/project notes |
| `python-patterns` / `python-testing` | New code in `rag/` |
| `e2e-testing` / `e2e` | UI changes in `rag/static/` |
| `iterative-retrieval` | Agentic RAG / context refinement |
| `cost-aware-llm-pipeline` | Model routing decisions |
| `verification-loop` | Before declaring a feature done |
| `tdd-workflow` | New feature or bug fix |
| `claude-mem:mem-search` | Searching past decisions, session context |
| `claude-mem:smart-explore` | Codebase exploration across sessions |
| `ui-ux-pro-max:ui-ux-pro-max` | Chat UI design and UX decisions |
| `frontend-design:frontend-design` | Frontend layout, CSS, component design |
| `caveman` | Default on — keep outputs tight |

### Automation Hooks (Ingestion Orchestration)

Local watching is the floor, external orchestration is the ceiling.

- **`rag/watcher.py` (watchdog)** — Already shipped. Debounced 3s file-system observer triggers `python -m rag.ingest --file <path>` on `.md` create/modify. Skip list covers `_publish`, `.obsidian`, `.git`, `rag`, `node_modules`.
- **n8n workflow (preferred for remote vaults).** Webhook → vault sync (rsync) → `ingest.py --changed` → Qdrant health check → Slack/Discord notification. Define in `automation/n8n/nexus-ingest.json`.
- **Make.com fallback.** For folks without n8n, mirror the same flow with HTTP modules. Document under `automation/make/README.md`.
- **GitHub Actions.** On push to `main`, run `ingest.py --changed` against the production Qdrant if the diff touches `.md` files outside `04 - Archive/`. Workflow under `.github/workflows/reindex.yml`.

When designing any new ingestion path, register it as an "ingestion source" — give it a name, document its dedup behavior, wire it through the same metadata-extraction pass used by `ingest.py`. **No bypass paths.**

---

## 3. Execution Directives — Agentic RAG

You operate as an **agent over this repo**, not as a passive responder. The following directives are non-negotiable.

### 3.1 Ambiguity → Tool Use, Not Guessing

If the user's query is ambiguous (vague nouns, missing scope, unspecified time window):
1. **Probe the vault metadata first.** Use Filesystem MCP or Vector DB MCP to list candidate folders, tags, or recent notes that disambiguate.
2. **Refine the query string** based on what you found, then re-run retrieval.
3. **Only then** ask the user — and when you ask, present the candidates you've already located ("Did you mean X (in Projects) or Y (in Archive)?").

### 3.2 Evaluate Retrieved Context Before Generating

Before composing the final answer:
- Check that retrieved chunks **actually mention** the query terms (sparse arm sanity).
- Check `rerank_score` of the top result; if below `RERANK_CONFIDENCE_FLOOR` (default `0.30`), trigger one **query rewrite** loop (prompt a small model to rephrase) and re-retrieve. Cap rewrites at 1.
- If still below floor, generate an **honest abstention**: "Vault doesn't cover this confidently; here is what's adjacent." Do not hallucinate.

### 3.3 Multi-Hop via Knowledge Graph

When a query references entities that exist as Obsidian wikilinks (people, projects, concepts, entities):
1. Resolve the entity to its note via Knowledge Graph MCP / ConPort.
2. Expand context with one-hop neighbors (notes that wikilink in or out).
3. Pass the expanded set through the reranker — do not blindly stuff context.

### 3.4 Self-Grade Before Streaming

After generating the answer (and before streaming it to the user surface), self-check:
- **Citation coverage.** Every factual sentence has at least one `[n]` citation.
- **Citation pointability.** Every `[n]` resolves to a chunk actually present in the retrieved set.
- **Refusal honesty.** If you abstained, the reasons match the evidence in the trace.

Failures go into the trace log with a `selfgrade.fail` event and trigger one regeneration.

### 3.5 Write-Back Loop

When you produce a synthesis the user accepts, propose persisting it to the vault as a Concept or Synthesis note via `obsidian-second-brain`. The vault is self-rewriting; today's answer is tomorrow's retrieved chunk.

---

## 4. Quality & Evaluation Standards

### 4.1 Code Quality

- **TDD is the default.** New features start with a failing test under `rag/tests/`. Use `tdd-workflow`. Target 80%+ line coverage on changed files.
- **Type-checked.** All new code uses PEP 484 type hints; `mypy --strict` clean on changed modules.
- **Linted & formatted.** `ruff check` and `ruff format` pass before commit. No `# type: ignore` without a comment naming the reason.
- **Async-first.** Network I/O (Qdrant, Groq, Obsidian writes) uses async; never block the event loop. SQLite via `aiosqlite`.
- **Secrets in env, never in code.** `python-dotenv` for local; deploy via systemd env files on the VPS. Never echo secrets to logs.
- **Errors propagate.** No silent `except:` — audit for silent failures if tempted. Catch what you can recover from; log and re-raise the rest.
- **DRY/YAGNI/KISS.** No abstractions for hypothetical futures. Three lines duplicated beats one wrong abstraction.

### 4.2 Observability

Build the system so it can be evaluated. Every retrieval produces an artifact.

- **Trace store.** Append-only JSONL at `rag/data/traces/YYYY-MM-DD.jsonl`. Each row contains: `query_id`, `query_raw`, `query_rewritten` (if any), `filters`, candidate IDs at each pipeline stage with their scores (`bm25_rank`, `dense_rank`, `rrf_score`, `rerank_score`), the final top-K, the LLM input messages, the streamed answer, citation set, latency per stage, model versions, and (later) the user feedback verdict.
- **OpenTelemetry spans.** One span per pipeline stage; export to the Dashboard router for live inspection.
- **Health endpoints.** `/health/qdrant`, `/health/groq`, `/health/watcher` already exist — extend with `/health/reranker` and `/health/bm25` when those land.

### 4.3 RAG Evaluation — RAGAS

A retrieval system without measurement is a guess.

- **Framework.** [RAGAS](https://github.com/explodinggradients/ragas), pinned via `pyproject.toml`.
- **Metrics.** At minimum: **Context Precision**, **Context Recall**, **Faithfulness**, **Answer Relevance**. Add **Context Entities Recall** once GraphRAG is in place.
- **Golden dataset.** `rag/data/eval/golden_qa.jsonl` — question + ground-truth answer + expected source files. Seed with 50 hand-curated Q/A pairs drawn from real vault notes. Expand to 200+ over time.
- **Eval harness.** `rag/scripts/eval/run_ragas.py` — reads golden set, runs the live pipeline (or a frozen snapshot via `RAG_EVAL_MODE=snapshot`), produces a Markdown report at `rag/data/eval/reports/YYYY-MM-DD-<sha>.md` and a CSV.
- **CI gate.** Block PRs that drop Context Precision or Context Recall by more than 5% vs. the last `main` baseline. Configure in `.github/workflows/rag-eval.yml`.
- **Per-PR diff report.** When a PR changes anything under `rag/`, post the eval delta as a PR comment.

### 4.4 Definition of Done

A change to `rag/` is **done** when:
- [ ] Tests pass (`pytest rag/tests`).
- [ ] Coverage ≥ 80% on changed lines.
- [ ] `ruff` + `mypy` clean.
- [ ] RAGAS metrics did not regress > 5% vs `main`.
- [ ] Trace store schema is unchanged or migrated.
- [ ] Health endpoints return green.
- [ ] If user-facing: E2E (Playwright) covers the new flow.
- [ ] Dev log written to `Dev Logs/YYYY-MM-DD — <Title>.md`.

---

## Project Operations

### Local Dev

```bash
# install
cd rag && uv sync

# run API
uv run uvicorn rag.app:app --reload --port 8000

# ingest the whole vault
uv run python -m rag.ingest

# incremental
uv run python -m rag.ingest --changed

# tests
uv run pytest rag/tests -v --cov=rag

# eval (once harness lands)
uv run python rag/scripts/eval/run_ragas.py
```

### Vault Layout (PARA)

- `00 - Inbox/` — capture zone; processed daily.
- `01 - Projects/` — active, dated outcomes.
- `02 - Areas/` — ongoing responsibilities.
- `03 - Resources/` — reference, organized by topic.
- `04 - Archive/` — completed or inactive.
- `05 - Daily Notes/` — journal entries.
- `06 - Concepts/` — atomic Zettelkasten notes.
- `07 - Entities/` — people, companies, tools, products.
- `Dev Logs/` — engineering work logs.
- `_publish/` — Quartz v4 publishing pipeline (output: nexus.gayo-sphere.cloud).
- `rag/` — this RAG system.

### Deploy

- **Quartz publish:** `./deploy-nexus.sh` — rsync built `_publish/public/` to the VPS. Serves https://nexus.gayo-sphere.cloud. Requires Node ≥22 (the script does `nvm use 22` automatically).
- **RAG deploy:** `./deploy-rag.sh` — rsync vault + code, full reindex, restart `nexus-chat` systemd unit. Serves **https://chat.nexus.gayo-sphere.cloud**.
  - systemd unit: `/etc/systemd/system/nexus-chat.service`. `ExecStart=/root/.local/bin/uv run uvicorn app:app --host 127.0.0.1 --port 8501`. `EnvironmentFile=/home/nexus-rag/.env`. `Restart=always`.
  - nginx proxies `chat.nexus.gayo-sphere.cloud` → `127.0.0.1:8501` (CloudPanel-managed, Let's Encrypt SSL).
  - VPS `.env` is preserved across deploys (`rsync --exclude='.env'`). Rotate keys by editing `/home/nexus-rag/.env` directly, then `systemctl restart nexus-chat`.
  - Post-deploy verify: `curl -sSI https://chat.nexus.gayo-sphere.cloud/` → 200; `ssh root@72.62.196.231 systemctl is-active nexus-chat` → `active`; `journalctl -u nexus-chat -n 50` for boot logs.
- **Qdrant:** Container `qdrant-nexus` on the VPS, port 6333 (Docker), data at `/home/nexus-qdrant/storage/`. Public HTTPS at `https://qdrant.nexus.gayo-sphere.cloud:443` (Mac dev path; the VPS itself talks to `http://127.0.0.1:6333` directly — no tunnel needed anywhere).

### Environment

`rag/.env` (Mac dev, gitignored) and `/home/nexus-rag/.env` (VPS prod, edited in place) must define: `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION=nexus-vault`, `EMBED_MODEL=BAAI/bge-small-en-v1.5`, `GROQ_MODEL=llama-3.3-70b-versatile`, `FOLLOWUP_MODEL=llama-3.1-8b-instant`, `JWT_SECRET` (random ≥32 bytes), `NEXUS_PASSWORD`, `VAULT_PATH`.

The two environments differ on:
- `QDRANT_URL` — Mac: `https://qdrant.nexus.gayo-sphere.cloud:443`. VPS: `http://127.0.0.1:6333`.
- `VAULT_PATH` — Mac: vault root on local disk. VPS: `/home/nexus-vault`.

---

## Working With This Repo (Rules for Claude)

1. **Read this file first.** Every session.
2. **Use the tools you have.** MCP servers > guessing. Skills > improvising.
3. **Plan before code.** For anything bigger than a one-line change, use `/plan` (built-in plan mode) and save to `docs/plans/`.
4. **TDD for new behavior.** Failing test → minimal impl → green → refactor → commit.
5. **Cite or abstain.** If the vault doesn't cover it, say so.
6. **Trace everything.** No silent retrieval — every query writes to the trace store.
7. **Caveman by default.** Keep output tight. The user reads the diff.
8. **Write to the vault when you learn.** Conversations should leave artifacts.

## 6. The Principal Architect Protocol (AI-to-AI Collaboration)

You (Claude) are collaborating with an external AI Principal Architect (Gemini) who is guiding the overarching system design. The human user is the secure relay between you two. When you receive a prompt formatted as `> System Directive: Phase X`, you are receiving instructions from the Architect. 

To ensure flawless collaboration, you must adhere strictly to this protocol:

### 6.1 The "Hands and Eyes" Rule
The Architect has deep reasoning capabilities but **zero direct access** to this codebase, the VPS, or the terminal. You are the hands and eyes. If the Architect's hypothesis is contradicted by local logs, code state, or runtime behavior, **you must push back**. Provide the raw data, explain why the directive might fail, and propose a superior alternative. 

### 6.2 The Mandatory Stop (Plan Before Execution)
When given a multi-step Directive, **you must never execute code changes or deploy immediately.** 1. Perform the necessary read-only diagnostics (grep logs, inspect files, run tests).
2. Generate a highly detailed `Phase X Plan` in Markdown (Context, Diagnostic Findings, Engineering Plan, Critical Files, Verification Steps).
3. **STOP.** Output the plan and explicitly state: *"Awaiting 'Plan Approved' from the Architect."* Do not proceed until the human user relays that exact authorization.

### 6.3 Diagnostic Formatting
When the Architect asks for logs, stack traces, or terminal outputs, format them in clean markdown blocks. Cut the noise and highlight the anomalies. Make it easy for the human to copy-paste your findings back to the Architect.

### 6.4 Proactive Consultation
If a directive introduces an edge case, a security risk, or a severe latency penalty, pause and ask the Architect a clarifying question. Use multiple-choice options (e.g., "Option 1: Fast/Cheap vs. Option 2: Slow/Accurate") so the Architect can quickly make a strategic decision.

> "The vault is the source of truth. The RAG layer is the cortex. The agent is the will. Keep all three honest."
