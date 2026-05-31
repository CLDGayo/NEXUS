# NEXUS - All Tests

Last updated: 2026-05-31 (STUDY phase)

Attach this file first when the task involves testing, verification, or test debugging.

This is the fast operator guide for the testing surface:

- which runner to use
- what command to start with
- how to quickly debug common failures
- which deeper file to read next

Do not load the whole `process/context/tests/` folder by default. Start here, then drill down.

---

## How This File Works

This is the `all-tests.md` entrypoint for the `tests/` context group. Agents read `all-context.md` first and get routed here for testing tasks. This file gives quick decision rules and commands. Add deeper docs (e.g., `e2e-tests.md`, `debugging-and-pitfalls.md`) and routing rows as the surface grows.

---

## What This Covers

- test runner selection (pytest; Playwright for the SPA)
- quick commands
- ruff / mypy verification gates
- current testing gaps

## Read This When

- running tests after implementation
- deciding between runners (pytest vs Playwright)
- debugging failing tests
- checking the lint/type gates before a commit

## Quick Routing

(No deeper test docs yet. Add routing entries here as they are created.)

## Quick Decision Guide

### Use `pytest` for everything in `rag/`

- All Python unit/integration tests run through **pytest** via **uv**.
- `asyncio_mode = auto` — `async def test_*` functions run without an explicit `@pytest.mark.asyncio`.
- Markers: `unit` (fast, isolated) and `integration` (multiple modules / mocked externals).
- 96 test files across 7 dirs: `rag/tests/`, `rag/orchestrator/tests/`, `rag/messenger/tests/`, `rag/retrieval/tests/`, `rag/guardrails/tests/`, `rag/ingest_v2/tests/`, `rag/observability/tests/`.
- External services are mocked: `fakeredis` (Redis), `moto[s3,server]` (MinIO/S3). No live Qdrant/Groq/Postgres needed for unit tests.

### Use Playwright when

- the behavior depends on the real chat SPA (`rag/static/`) — SSE streaming, auth gate, citation rendering.
- Playwright MCP is configured for E2E of the RAG SPA.

## Default Verification Order

1. run the narrowest existing automated test (single file / single subpackage)
2. unit/integration (pytest) before browser tests
3. Playwright only when the real UI is the thing being verified

## Commands

Run from the **repo root** (pytest `pythonpath=[".."]` resolves `rag.*` the way the container does). All commands go through `uv` against the `rag/` project.

| Scope | Command |
|---|---|
| full suite + coverage | `uv run --project rag pytest rag/tests -v --cov=rag` |
| single subpackage | `uv run --project rag pytest rag/messenger/tests -v` |
| single file | `uv run --project rag pytest rag/orchestrator/tests/test_sales_tools.py -v` |
| by marker | `uv run --project rag pytest rag -m unit` / `-m integration` |
| keyword filter | `uv run --project rag pytest rag -k hitl` |

**Lint / format (ruff):**
```bash
uv run --project rag ruff check rag
uv run --project rag ruff format rag
```

**Type check (mypy --strict, scoped):** strict gate applies only to modules listed under `[tool.mypy].files` in `rag/pyproject.toml` (currently `rag/routers/admin_users.py`, `rag/routers/profile.py`, `rag/services`, `rag/scripts/phase28_bootstrap_minio.py`).
```bash
uv run --project rag mypy --config-file rag/pyproject.toml
```

## Debugging Quick Reference

- **Import errors (`from rag.X import Y` fails):** run from **repo root**, not from inside `rag/`. `pythonpath=[".."]` is set in `rag/pyproject.toml`.
- **Async tests "not awaited" / skipped:** rely on `asyncio_mode = auto`; do not also add conflicting `@pytest.mark.asyncio(...)` loop scopes.
- **S3 / MinIO tests:** use `moto` — no real MinIO. Avatar-upload tests (Phase 28) need `moto[s3,server]`.
- **Redis-touching code:** `fakeredis` substitutes; no live Redis.
- **mypy noise on old modules:** strict is intentionally scoped — `rag.auth.*` is softened and v1/v2 modules are excluded. Only add a module to `files` once it is strict-clean.
- **Graph DB tests:** `rag/ingest_v2/graph_db.py` uses an on-disk SQLite (`rag/data/nexus_graph.db`); tests should use a temp path, not the real DB.

## Known Gaps

- **No RAGAS eval harness yet.** Target per old CLAUDE.md: `rag/scripts/eval/run_ragas.py` + golden set `rag/data/eval/golden_qa.jsonl` (Context Precision/Recall/Faithfulness/Answer Relevance), CI gate on >5% regression. Not built.
- **No trace-store assertions.** Append-only JSONL trace store (`rag/data/traces/`) is part of the target observability design; coverage for it is thin.
- **Hybrid-retrieval tests** cover dense only — BM25 + RRF arm not shipped, so no fusion tests exist.
- **Coverage target is 80%+ on changed lines** (per project DoD) but is not enforced by a CI gate in-repo yet.
