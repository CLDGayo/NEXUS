# Testing

NEXUS tests are hermetic, async-first, and phase-numbered. 96 test files across 7 directories cover the RAG pipeline, API routers, authentication, and subsystems.

---

## Philosophy

- **Hermetic** — each test owns its fixtures; no shared mutable state
- **Async-first** — `asyncio_mode = auto`; all test functions are `async def`
- **Phase-numbered** — test files prefixed with phase number (`test_p27_auth.py`) trace to the feature that introduced them
- **Real database** — integration tests hit a real Postgres and Qdrant instance; no mocking of core dependencies

> **📝 NOTE:** Do not mock the database in integration tests. NEXUS was burned by mock/prod divergence in the past where mocked tests passed but production migrations failed.

---

## Test Directory Map

```
rag/tests/                         # Root suite: pipeline + cross-cutting
rag/auth/tests/                    # IAM, JWT, fastapi-users integration
rag/retrieval/tests/               # Dense, sparse, graph, RRF, rerank
rag/ingest_v2/tests/               # Layout-aware chunking, metadata extraction
rag/guardrails/tests/              # CitationValidator, ExactMatch, Entropy
rag/messenger/tests/               # Webhook, triage, HITL, coalesce
rag/orchestrator/tests/            # LangGraph nodes, routing, state
```

---

## Markers

| Marker | Meaning | Run with |
|---|---|---|
| `unit` | No external deps; fast | `pytest -m unit` |
| `integration` | Requires Postgres + Qdrant + Redis | `pytest -m integration` |
| (no marker) | Default — runs in both contexts | `pytest` |

---

## Quick Commands

```bash
cd rag

# All tests
uv run pytest

# Unit tests only (fast, no infra required)
uv run pytest -m unit

# Integration tests
uv run pytest -m integration

# Single file
uv run pytest tests/test_retrieval.py

# With coverage
uv run pytest --cov=rag --cov-report=term-missing

# Verbose output
uv run pytest -v
```

---

## Section Contents

| Doc | Description |
|---|---|
| [Test Structure](test-structure.md) | Directory map, markers, fixture patterns |
| [Running Tests](running-tests.md) | Commands, CI config, coverage gates |
| [Writing Tests](writing-tests.md) | Patterns: async fixtures, fakeredis, moto S3 |

---

## Coverage Gate

Target: **80%+** overall. Run to check:

```bash
uv run pytest --cov=rag --cov-report=term-missing --cov-fail-under=80
```

---

## Related Docs

- [Context — Tests](../process/context/tests/all-tests.md) — authoritative test runner reference
- [RAG Pipeline](../02-rag-pipeline/README.md)
- [Deployment](../12-deployment/README.md) — migrations must pass before test suite
