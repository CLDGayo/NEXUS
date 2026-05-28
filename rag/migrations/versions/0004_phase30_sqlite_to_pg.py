"""Phase 30.1 — SQLite legacy eradication.

Revision ID: 0004_phase30_sqlite_to_pg
Revises: 0003_phase29_messenger_page_tenants
Create Date: 2026-05-27

Promotes the last five aiosqlite-resident tables to Postgres and
transfers every row from ``rag/data/nexus.db`` (or the path supplied via
``NEXUS_SQLITE_PATH``) into the new ``app.*`` tables.

Tables created:
    * ``app.conversations`` — UUID PK, strict ``user_id`` / ``tenant_id`` FKs.
    * ``app.messages`` — UUID PK, FK CASCADE to ``conversations``.
    * ``app.api_tokens`` — UUID PK, optional ``user_id`` FK.
    * ``app.integrations`` — UUID PK, JSONB ``config``, boolean ``enabled``.
    * ``app.settings`` — TEXT PK, JSONB ``value``.

Slug reconciliation (Architect ruling **B — rewrite SQLite slugs**) is
applied in-memory via the ``SLUG_REWRITES`` map: legacy ``tenant_id``
slugs are translated before the slug→UUID lookup. The source SQLite file
is opened read-only and never mutated.

Orphan policy (Architect ruling **Strict skip + JSONL log**): rows whose
``tenant_id`` slug or ``user_id`` UUID cannot be resolved in the target
Postgres are skipped and appended as JSON Lines to
``rag/data/traces/0004-orphans.jsonl`` (overridable via
``NEXUS_ORPHAN_LOG``). A run-summary line is emitted at INFO.

Idempotency: every INSERT uses ``ON CONFLICT DO NOTHING``. Re-running
``alembic upgrade head`` after the first successful pass is a no-op.

Downgrade is **not** supported. Restore ``rag/data/nexus.db`` from a
deploy-time backup and re-stamp ``0003_phase29_messenger_page_tenants``
to roll back.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0004_phase30_sqlite_to_pg"
down_revision = "0003_phase29_messenger_page_tenants"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration.phase30")

ORPHAN_LOG = Path(
    os.environ.get("NEXUS_ORPHAN_LOG", "rag/data/traces/0004-orphans.jsonl")
)
SQLITE_PATH = Path(
    os.environ.get("NEXUS_SQLITE_PATH", "rag/data/nexus.db")
)

# Architect ruling B: rewrite legacy slugs in-memory before resolving
# them against ``app.tenants.slug``. The SQLite source file is never
# touched. Add more entries here if future tenants ever need rebranding.
SLUG_REWRITES: dict[str, str] = {"hunter": "cozy-downloads-store"}

BATCH_SIZE = 500


# ─── DDL ─────────────────────────────────────────────────────────────────────


def _create_tables() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_app_conversations_user_id",
        "conversations",
        ["user_id"],
        schema="app",
    )
    op.create_index(
        "ix_app_conversations_tenant_id",
        "conversations",
        ["tenant_id"],
        schema="app",
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["app.conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_app_messages_conversation_id",
        "messages",
        ["conversation_id"],
        schema="app",
    )
    op.create_index(
        "ix_app_messages_user_id", "messages", ["user_id"], schema="app"
    )
    op.create_index(
        "ix_app_messages_tenant_id",
        "messages",
        ["tenant_id"],
        schema="app",
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=32), nullable=False),
        sa.Column("scopes_csv", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema="app",
    )
    op.create_index(
        "ix_app_api_tokens_user_id",
        "api_tokens",
        ["user_id"],
        schema="app",
    )

    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "config", sa.dialects.postgresql.JSONB(), nullable=False
        ),
        sa.Column(
            "events_csv",
            sa.String(length=1024),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_fired_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_status", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
        schema="app",
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_ts(value: str | None) -> datetime | None:
    """Parse SQLite ISO-8601 timestamp; tolerate trailing ``Z``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _log_orphan(table: str, row_id: object, reason: str) -> None:
    ORPHAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ORPHAN_LOG.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "table": table,
                    "id": str(row_id),
                    "reason": reason,
                }
            )
            + "\n"
        )


def _safe_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None or raw == "":
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        return None


def _resolve_tenant(
    raw_slug: Any, slug_to_uuid: Mapping[str, uuid.UUID]
) -> uuid.UUID | None:
    if raw_slug is None:
        return None
    slug = SLUG_REWRITES.get(str(raw_slug), str(raw_slug))
    return slug_to_uuid.get(slug)


def _flush(bind: Any, sql: str, batch: list[dict[str, Any]]) -> None:
    if not batch:
        return
    bind.execute(sa.text(sql), batch)


# ─── Transfer routines ───────────────────────────────────────────────────────


def _transfer_conversations(
    src: sqlite3.Connection,
    bind: Any,
    slug_to_uuid: Mapping[str, uuid.UUID],
    valid_users: set[uuid.UUID],
) -> set[uuid.UUID]:
    """Transfer ``conversations`` rows. Returns the set of conversation
    UUIDs that survived the orphan filter so ``messages`` can validate
    parents without re-querying Postgres."""
    sql = """
        INSERT INTO app.conversations
            (id, title, user_id, tenant_id, created_at, updated_at)
        VALUES
            (:id, :title, :user_id, :tenant_id, :created_at, :updated_at)
        ON CONFLICT (id) DO NOTHING
    """
    accepted: set[uuid.UUID] = set()
    batch: list[dict[str, Any]] = []
    cur = src.execute(
        "SELECT id, title, created_at, updated_at, user_id, tenant_id "
        "FROM conversations"
    )
    for row in cur:
        conv_id = _safe_uuid(row["id"])
        if conv_id is None:
            _log_orphan("conversations", row["id"], "malformed conv id")
            continue
        user_id = _safe_uuid(row["user_id"])
        if user_id is None or user_id not in valid_users:
            _log_orphan(
                "conversations",
                row["id"],
                f"user_id unresolved: {row['user_id']!r}",
            )
            continue
        tenant_id = _resolve_tenant(row["tenant_id"], slug_to_uuid)
        if tenant_id is None:
            _log_orphan(
                "conversations",
                row["id"],
                f"tenant slug unresolved: {row['tenant_id']!r}",
            )
            continue
        created = _parse_ts(row["created_at"]) or datetime.utcnow()
        updated = _parse_ts(row["updated_at"]) or created
        batch.append(
            {
                "id": conv_id,
                "title": row["title"] or "",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "created_at": created,
                "updated_at": updated,
            }
        )
        accepted.add(conv_id)
        if len(batch) >= BATCH_SIZE:
            _flush(bind, sql, batch)
            batch.clear()
    _flush(bind, sql, batch)
    return accepted


def _transfer_messages(
    src: sqlite3.Connection,
    bind: Any,
    slug_to_uuid: Mapping[str, uuid.UUID],
    valid_users: set[uuid.UUID],
    valid_conversations: set[uuid.UUID],
) -> None:
    sql = """
        INSERT INTO app.messages
            (id, conversation_id, user_id, tenant_id, role, content,
             sources, created_at)
        VALUES
            (:id, :conversation_id, :user_id, :tenant_id, :role, :content,
             :sources, :created_at)
        ON CONFLICT (id) DO NOTHING
    """
    batch: list[dict[str, Any]] = []
    cur = src.execute(
        "SELECT id, conversation_id, role, content, sources, "
        "created_at, user_id, tenant_id FROM messages"
    )
    for row in cur:
        msg_id = _safe_uuid(row["id"])
        conv_id = _safe_uuid(row["conversation_id"])
        if msg_id is None or conv_id is None:
            _log_orphan("messages", row["id"], "malformed id/parent id")
            continue
        if conv_id not in valid_conversations:
            _log_orphan(
                "messages",
                row["id"],
                f"parent conversation orphaned: {row['conversation_id']!r}",
            )
            continue
        user_id = _safe_uuid(row["user_id"])
        if user_id is None or user_id not in valid_users:
            _log_orphan(
                "messages",
                row["id"],
                f"user_id unresolved: {row['user_id']!r}",
            )
            continue
        tenant_id = _resolve_tenant(row["tenant_id"], slug_to_uuid)
        if tenant_id is None:
            _log_orphan(
                "messages",
                row["id"],
                f"tenant slug unresolved: {row['tenant_id']!r}",
            )
            continue
        sources: Any = None
        if row["sources"]:
            try:
                sources = json.loads(row["sources"])
            except json.JSONDecodeError:
                _log_orphan(
                    "messages",
                    row["id"],
                    "sources column not valid JSON; stored as null",
                )
                sources = None
        batch.append(
            {
                "id": msg_id,
                "conversation_id": conv_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "role": row["role"] or "user",
                "content": row["content"] or "",
                "sources": (
                    json.dumps(sources) if sources is not None else None
                ),
                "created_at": _parse_ts(row["created_at"])
                or datetime.utcnow(),
            }
        )
        if len(batch) >= BATCH_SIZE:
            _flush(bind, sql, batch)
            batch.clear()
    _flush(bind, sql, batch)


def _transfer_api_tokens(
    src: sqlite3.Connection,
    bind: Any,
    valid_users: set[uuid.UUID],
) -> None:
    sql = """
        INSERT INTO app.api_tokens
            (id, name, token_hash, prefix, scopes_csv, created_at,
             last_used_at, revoked_at, user_id)
        VALUES
            (:id, :name, :token_hash, :prefix, :scopes_csv, :created_at,
             :last_used_at, :revoked_at, :user_id)
        ON CONFLICT (token_hash) DO NOTHING
    """
    batch: list[dict[str, Any]] = []
    cur = src.execute(
        "SELECT id, name, token_hash, prefix, scopes_csv, created_at, "
        "last_used_at, revoked_at, user_id FROM api_tokens"
    )
    for row in cur:
        user_id = _safe_uuid(row["user_id"])
        if row["user_id"] not in (None, "") and user_id is None:
            _log_orphan(
                "api_tokens",
                row["id"],
                f"malformed user_id: {row['user_id']!r}",
            )
            continue
        if user_id is not None and user_id not in valid_users:
            _log_orphan(
                "api_tokens",
                row["id"],
                f"user_id not in app.users: {row['user_id']!r}",
            )
            continue
        batch.append(
            {
                "id": uuid.uuid4(),
                "name": row["name"] or "",
                "token_hash": row["token_hash"],
                "prefix": row["prefix"] or "",
                "scopes_csv": row["scopes_csv"] or "",
                "created_at": _parse_ts(row["created_at"])
                or datetime.utcnow(),
                "last_used_at": _parse_ts(row["last_used_at"]),
                "revoked_at": _parse_ts(row["revoked_at"]),
                "user_id": user_id,
            }
        )
        if len(batch) >= BATCH_SIZE:
            _flush(bind, sql, batch)
            batch.clear()
    _flush(bind, sql, batch)


def _transfer_integrations(
    src: sqlite3.Connection, bind: Any
) -> None:
    sql = """
        INSERT INTO app.integrations
            (id, type, name, config, events_csv, enabled, created_at,
             updated_at, last_fired_at, last_status)
        VALUES
            (:id, :type, :name, CAST(:config AS JSONB), :events_csv,
             :enabled, :created_at, :updated_at, :last_fired_at,
             :last_status)
    """
    batch: list[dict[str, Any]] = []
    cur = src.execute(
        "SELECT id, type, name, config_json, events_csv, enabled, "
        "created_at, updated_at, last_fired_at, last_status FROM integrations"
    )
    for row in cur:
        try:
            config = json.loads(row["config_json"] or "{}")
        except json.JSONDecodeError:
            _log_orphan(
                "integrations",
                row["id"],
                "config_json not valid JSON",
            )
            continue
        batch.append(
            {
                "id": uuid.uuid4(),
                "type": row["type"] or "",
                "name": row["name"] or "",
                "config": json.dumps(config),
                "events_csv": row["events_csv"] or "",
                "enabled": bool(row["enabled"]),
                "created_at": _parse_ts(row["created_at"])
                or datetime.utcnow(),
                "updated_at": _parse_ts(row["updated_at"])
                or datetime.utcnow(),
                "last_fired_at": _parse_ts(row["last_fired_at"]),
                "last_status": row["last_status"],
            }
        )
        if len(batch) >= BATCH_SIZE:
            _flush(bind, sql, batch)
            batch.clear()
    _flush(bind, sql, batch)


def _transfer_settings(src: sqlite3.Connection, bind: Any) -> None:
    sql = """
        INSERT INTO app.settings (key, value, updated_at)
        VALUES (:key, CAST(:value AS JSONB), :updated_at)
        ON CONFLICT (key) DO NOTHING
    """
    batch: list[dict[str, Any]] = []
    cur = src.execute("SELECT key, value, updated_at FROM settings")
    for row in cur:
        try:
            value = json.loads(row["value"] or "null")
        except json.JSONDecodeError:
            _log_orphan(
                "settings",
                row["key"],
                "value not valid JSON",
            )
            continue
        batch.append(
            {
                "key": row["key"],
                "value": json.dumps(value),
                "updated_at": _parse_ts(row["updated_at"])
                or datetime.utcnow(),
            }
        )
    _flush(bind, sql, batch)


def _table_exists(src: sqlite3.Connection, name: str) -> bool:
    cur = src.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


def _scalar_set(bind: Any, query: str) -> set[Any]:
    return {row[0] for row in bind.execute(sa.text(query))}


def _slug_lookup(bind: Any) -> dict[str, uuid.UUID]:
    return {
        row.slug: row.id
        for row in bind.execute(
            sa.text("SELECT id, slug FROM app.tenants")
        )
    }


def _iter_transfers(
    src: sqlite3.Connection,
    bind: Any,
) -> Iterable[str]:
    slug_to_uuid = _slug_lookup(bind)
    valid_users = _scalar_set(bind, "SELECT id FROM app.users")

    if _table_exists(src, "conversations"):
        accepted = _transfer_conversations(
            src, bind, slug_to_uuid, valid_users
        )
        yield f"conversations: {len(accepted)} transferred"
        if _table_exists(src, "messages"):
            _transfer_messages(
                src, bind, slug_to_uuid, valid_users, accepted
            )
            yield "messages: transferred"
    if _table_exists(src, "api_tokens"):
        _transfer_api_tokens(src, bind, valid_users)
        yield "api_tokens: transferred"
    if _table_exists(src, "integrations"):
        _transfer_integrations(src, bind)
        yield "integrations: transferred"
    if _table_exists(src, "settings"):
        _transfer_settings(src, bind)
        yield "settings: transferred"


# ─── Entry points ────────────────────────────────────────────────────────────


def upgrade() -> None:
    _create_tables()

    if not SQLITE_PATH.exists():
        logger.info(
            "phase30: no SQLite source at %s — DDL-only migration",
            SQLITE_PATH,
        )
        return

    bind = op.get_bind()
    src = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        for summary in _iter_transfers(src, bind):
            logger.info("phase30: %s", summary)
    finally:
        src.close()
    logger.info("phase30: transfer complete; orphan log at %s", ORPHAN_LOG)


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 30.1 is one-way. Restore rag/data/nexus.db from backup, "
        "then `alembic stamp 0003_phase29_messenger_page_tenants`."
    )
