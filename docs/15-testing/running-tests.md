# Running Tests

All commands run from `rag/` using `uv run pytest`.

---

## Prerequisites

**Unit tests:** no infra required.

**Integration tests:** requires running:
- Postgres (with migrations applied: `uv run alembic upgrade head`)
- Qdrant (`docker compose up -d qdrant-nexus`)
- Redis (`docker compose up -d redis`)

Env vars must be set in `rag/.env` (or exported):

```bash
DATABASE_URL=postgresql+asyncpg://nexus_rag:password@localhost:5432/nexus_rag
QDRANT_URL=http://127.0.0.1:6333
REDIS_URL=redis://localhost:6379
```

---

## Command Reference

```bash
cd rag

# Full suite
uv run pytest

# Unit only (no infra)
uv run pytest -m unit

# Integration only
uv run pytest -m integration

# Single file
uv run pytest tests/test_chat.py

# Single test by name
uv run pytest -k "test_dense_retrieval"

# Stop on first failure
uv run pytest -x

# Verbose — show test names
uv run pytest -v

# Show print/log output
uv run pytest -s

# Coverage report
uv run pytest --cov=rag --cov-report=term-missing

# Coverage with HTML output
uv run pytest --cov=rag --cov-report=html
# Opens: rag/htmlcov/index.html

# Coverage gate (fail if < 80%)
uv run pytest --cov=rag --cov-fail-under=80

# Run specific directory
uv run pytest retrieval/tests/

# Parallel execution (requires pytest-xdist)
uv run pytest -n auto
```

---

## Ruff + Mypy Gates

Tests are preceded by linting and type checking in CI:

```bash
# Lint
uv run ruff check rag/

# Format check
uv run ruff format --check rag/

# Type check (strict modules only)
uv run mypy rag/
```

Ruff and mypy must pass before pytest runs in CI.

---

## CI Configuration

GitHub Actions runs on every push to `main` and on PRs:

```yaml
# .github/workflows/test.yml (excerpt)
- name: Run linting
  run: uv run ruff check rag/ && uv run ruff format --check rag/

- name: Run type check
  run: uv run mypy rag/

- name: Run tests
  run: uv run pytest -m "not integration" --cov=rag --cov-fail-under=80
  env:
    DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}
    QDRANT_URL: http://localhost:6333
```

Integration tests run in a separate job with service containers (Postgres, Qdrant, Redis).

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `asyncpg.exceptions.ConnectionDoesNotExistError` | Postgres not running | `docker compose up -d` or start local Postgres |
| `qdrant_client.http.exceptions.UnexpectedResponse` | Qdrant collection missing | Run ingest: `uv run python -m rag.ingest` |
| `redis.exceptions.ConnectionError` | Redis not running | `docker compose start redis` |
| `alembic.exc.ProgrammingError: relation does not exist` | Migration not applied | `uv run alembic upgrade head` |
| `fixture 'X' not found` | `conftest.py` not on `pythonpath` | Ensure `pythonpath = [".."]` in `pyproject.toml` |

---

## Related Docs

- [Test Structure](test-structure.md)
- [Writing Tests](writing-tests.md)
- [Docker Compose Guide](../12-deployment/docker-compose-guide.md)
