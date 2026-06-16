# Test Structure

Directory layout, naming conventions, markers, and fixture organization across the 96-file test suite.

---

## Directory Map

```
rag/
  tests/                          # Root suite
    conftest.py                   # Shared fixtures: db session, qdrant client, tenant factory
    test_chat.py                  # Chat endpoint + SSE stream
    test_ingest.py                # v1 ingest pipeline
    test_retrieval.py             # Hybrid retrieval integration
    test_p31_graph_retrieval.py   # Phase 31: Postgres graph arm
    test_p37_hitl.py              # Phase 37: HITL pause/resume
    ...

  auth/tests/
    test_p27_jwt.py               # JWT login/logout/refresh
    test_p27_api_tokens.py        # nxs_ token create/revoke/scope

  retrieval/tests/
    test_dense.py                 # Qdrant dense arm
    test_sparse.py                # BM25 sparse arm
    test_rrf.py                   # RRF fusion
    test_rerank.py                # Cross-encoder reranker

  ingest_v2/tests/
    test_chunker.py               # Heading-tree chunking
    test_metadata.py              # Frontmatter extraction
    test_wikilinks.py             # Wikilink resolution

  guardrails/tests/
    test_citation_validator.py
    test_exactmatch_validator.py
    test_entropy_validator.py

  messenger/tests/
    test_p37_webhook.py           # HMAC verification
    test_p37_triage.py            # Intent classification
    test_coalesce.py              # Message coalescing

  orchestrator/tests/
    test_nodes.py                 # Individual node unit tests
    test_routing.py               # route_query_node decisions
    test_research_mode.py         # Multi-step research flow
```

---

## File Naming

| Pattern | Meaning |
|---|---|
| `test_{feature}.py` | Feature-scoped tests (no phase) |
| `test_p{NN}_{feature}.py` | Tests tied to a specific phase |
| `conftest.py` | Fixtures scoped to that directory |

Phase-prefixed names make it easy to find which tests cover a given phase's work.

---

## Markers

Applied per test or per file with `@pytest.mark.{marker}`:

```python
@pytest.mark.unit
async def test_rrf_fusion_empty_inputs():
    result = reciprocal_rank_fusion([], [], k=60)
    assert result == []

@pytest.mark.integration
async def test_dense_retrieval_returns_chunks(qdrant_client, tenant_fixture):
    chunks = await dense_retrieve("what is pricing", tenant_id="test-tenant", top_k=5)
    assert len(chunks) > 0
```

---

## conftest.py — Root Fixtures

Key fixtures available to all tests:

| Fixture | Scope | Provides |
|---|---|---|
| `db_session` | `function` | Async SQLAlchemy session, rolled back after each test |
| `qdrant_client` | `session` | Test Qdrant collection (separate from prod `nexus-vault`) |
| `redis_client` | `function` | `fakeredis.aioredis.FakeRedis()` |
| `tenant_fixture` | `function` | Pre-created tenant row + slug |
| `user_fixture` | `function` | Pre-created user + JWT token |
| `admin_fixture` | `function` | Admin user + token |
| `owner_fixture` | `function` | Owner user + token |

---

## asyncio_mode

All tests run async automatically. `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = [".."]
```

No `@pytest.mark.asyncio` needed per test.

---

## Related Docs

- [Running Tests](running-tests.md)
- [Writing Tests](writing-tests.md)
- [Context — Tests](../process/context/tests/all-tests.md)
