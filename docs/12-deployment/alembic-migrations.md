# Alembic Migrations

NEXUS uses Alembic for database schema management. All migrations live in `rag/migrations/versions/`.

---

## Configuration

`rag/alembic.ini` and `rag/migrations/env.py` configure Alembic to use `DATABASE_URL` from the environment.

```bash
# Run from rag/ directory
cd rag
```

All commands below assume `rag/` as the working directory.

---

## Common Commands

### Apply all pending migrations

```bash
uv run alembic upgrade head
```

Run on every deploy. Safe to re-run — already-applied migrations are skipped.

### Check current revision

```bash
uv run alembic current
```

### View migration history

```bash
uv run alembic history --verbose
```

### Downgrade one step

```bash
uv run alembic downgrade -1
```

### Downgrade to a specific revision

```bash
uv run alembic downgrade <revision_id>
```

---

## Creating a New Migration

### Auto-generate from SQLAlchemy models

```bash
uv run alembic revision --autogenerate -m "add_ai_settings_to_tenants"
```

Alembic compares the current database schema against your SQLAlchemy models and generates a diff. **Always review the generated file** — autogenerate can miss complex changes (partial indexes, custom constraints, enum types).

### Manual migration

```bash
uv run alembic revision -m "add_document_links_table"
```

Creates an empty revision file. Fill in `upgrade()` and `downgrade()` manually.

---

## Migration File Conventions

```python
# rag/migrations/versions/0011_add_ai_settings.py

"""add ai_settings to tenants

Revision ID: 0011abc
Revises: 0010def
Create Date: 2026-06-13
"""

def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("ai_settings", postgresql.JSONB(), nullable=True, server_default="{}"),
        schema="app"
    )

def downgrade() -> None:
    op.drop_column("tenants", "ai_settings", schema="app")
```

Key conventions:
- Sequential numeric prefix (`0011_`, `0012_`) in filename for easy ordering
- All tables use `schema="app"` (the `app` Postgres schema)
- Every `upgrade()` must have a matching `downgrade()`
- LangGraph tables (`langgraph.*`) are managed by LangGraph — do not create migrations for them

---

## Migration History (as of Phase 53)

| Revision | Description |
|---|---|
| 0001 | Initial schema: users, tenants, documents, conversations, messages |
| 0002 | Add products + product_images |
| 0003 | Add integrations table |
| 0004 | Add document_links (Phase 31 graph retrieval) |
| 0005 | Add system_prompts table |
| 0006 | Add api_tokens table |
| 0007 | Add logs table (audit trail) |
| 0008 | Add tenant_users RBAC + CHECK constraint (owner/admin/member) |
| 0009 | Add tenant_invites (SHA-256 token_hash, expires_at) |
| 0010 | Add avatar_url + archived_at to tenants |
| 0011 | Add ai_settings JSONB to tenants (Phase 45) |

---

## Production Deploy Procedure

Migrations always run before the service restarts:

```bash
# In deploy-rag.sh remote block:
uv run alembic upgrade head   # Step 1: migrate
sudo systemctl restart nexus-chat  # Step 2: restart
```

> **⚠️ WARNING:** Never restart the service before running migrations if new code depends on new columns. Always migrate first.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: relation "app.X" does not exist` | Migration not applied | `alembic upgrade head` |
| `Target database is not up to date` | Multiple heads in migration tree | `alembic heads` to see; merge with `alembic merge` |
| `Can't locate revision` | Revision file deleted | Restore from git history |
| Migration applied but column missing | Wrong schema | Ensure `schema="app"` in `op.add_column()` |

---

## Related Docs

- [RAG Deployment](rag-deployment.md) — migration step in deploy script
- [Prerequisites](prerequisites.md) — PostgreSQL setup
- [Orchestrator — State Persistence](../08-orchestrator/state-persistence.md) — LangGraph checkpointer tables
