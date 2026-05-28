"""Phase 31 — Document multi-tenancy and RBAC lockdown.

Revision ID: 0005_phase31_security_and_docs
Revises: 0004_phase30_sqlite_to_pg
Create Date: 2026-05-28

Creates the tenant-isolated document registry that eradicates the global
``rag/data/nexus_graph.db`` SQLite store, and adds ``tenant_id`` foreign
keys to ``app.api_tokens`` and ``app.integrations`` so the
``require_owner`` dependency can enforce row-level access on those
admin-class surfaces.

DDL changes:
    * ``app.documents`` — per-tenant file registry, UNIQUE (tenant_id, file).
    * ``app.document_links`` — per-tenant wikilink edges; replaces
      ``vault_links`` from the legacy SQLite graph.
    * ``app.api_tokens.tenant_id`` — NOT NULL FK; CASCADE on tenant delete.
    * ``app.integrations.tenant_id`` — NOT NULL FK; CASCADE on tenant delete.

Backfill policy (single-tenant production today):
    * ``api_tokens.tenant_id`` resolves via ``tenant_users`` lookup for
      each row's ``user_id`` (first owner-role membership wins). Tokens
      whose user has no owner membership are revoked; ``user_id IS NULL``
      tokens (pre-Phase-28 legacy) are deleted entirely.
    * ``integrations.tenant_id`` is set to the bootstrap tenant
      (``slug = 'cozy-downloads-store'``; falls back to the oldest tenant
      if the canonical slug isn't present). If the table is non-empty and
      no tenant exists, the migration aborts loudly.

The downgrade drops the new tables and the new FK columns. The previous
``nexus_graph.db`` file is NOT re-created on downgrade — its data is
considered lost the moment Phase 31 ships, and the v2 reindex is the
canonical re-population path.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0005_phase31_security_and_docs"
down_revision = "0004_phase30_sqlite_to_pg"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration.phase31")

CANONICAL_BOOTSTRAP_SLUG = "cozy-downloads-store"


# ─── DDL ─────────────────────────────────────────────────────────────────────


def _create_documents() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("file", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "aliases",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default="note",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "chunk_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "file", name="uq_app_documents_tenant_file"
        ),
        schema="app",
    )
    op.create_index(
        "ix_app_documents_tenant_id",
        "documents",
        ["tenant_id"],
        schema="app",
    )
    op.create_index(
        "ix_app_documents_tenant_archived",
        "documents",
        ["tenant_id", "archived_at"],
        schema="app",
    )


def _create_document_links() -> None:
    op.create_table(
        "document_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("src_document_id", sa.Uuid(), nullable=False),
        sa.Column("dst_target", sa.Text(), nullable=False),
        sa.Column("dst_document_id", sa.Uuid(), nullable=True),
        sa.Column("anchor", sa.Text(), nullable=False, server_default=""),
        sa.Column("alias", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["src_document_id"],
            ["app.documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dst_document_id"],
            ["app.documents.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "src_document_id",
            "dst_target",
            "anchor",
            name="uq_app_document_links_edge",
        ),
        schema="app",
    )
    op.create_index(
        "ix_app_document_links_tenant_dst",
        "document_links",
        ["tenant_id", "dst_document_id"],
        schema="app",
    )
    op.create_index(
        "ix_app_document_links_dst_target",
        "document_links",
        ["tenant_id", "dst_target"],
        schema="app",
    )


# ─── Backfill helpers ────────────────────────────────────────────────────────


def _pick_bootstrap_tenant(bind: Any) -> uuid.UUID | None:
    """Return the bootstrap tenant uuid.

    Prefers ``slug = CANONICAL_BOOTSTRAP_SLUG``; falls back to the oldest
    tenant row. Returns ``None`` only on a completely empty
    ``app.tenants`` table — callers must abort in that case.
    """

    row = bind.execute(
        sa.text("SELECT id FROM app.tenants WHERE slug = :slug LIMIT 1"),
        {"slug": CANONICAL_BOOTSTRAP_SLUG},
    ).first()
    if row is not None:
        return row[0]
    fallback = bind.execute(
        sa.text(
            "SELECT id FROM app.tenants ORDER BY created_at ASC LIMIT 1"
        )
    ).first()
    return fallback[0] if fallback else None


def _backfill_api_tokens(bind: Any) -> None:
    """Populate ``api_tokens.tenant_id`` for every existing row.

    1. NULL-user tokens (pre-Phase-28 system rows): delete outright. The
       Phase 30.1 docstring already warned these would be retired.
    2. Tokens whose owner has at least one ``owner``-role tenant_user
       row: bind to that tenant (the earliest one wins for determinism).
    3. Tokens whose owner has no owner-role membership: revoke
       (set ``revoked_at = now()``) and bind to the bootstrap tenant so
       the NOT NULL constraint holds. Operators can prune them later.
    """

    deleted_null = bind.execute(
        sa.text(
            "DELETE FROM app.api_tokens WHERE user_id IS NULL "
            "RETURNING id"
        )
    ).rowcount
    if deleted_null:
        logger.info(
            "phase31: deleted %s NULL-user api_tokens (pre-Phase-28 system rows)",
            deleted_null,
        )

    rows = bind.execute(
        sa.text(
            "SELECT t.id, t.user_id, "
            "(SELECT tu.tenant_id FROM app.tenant_users tu "
            " WHERE tu.user_id = t.user_id AND tu.role = 'owner' "
            " ORDER BY tu.created_at ASC LIMIT 1) AS tenant_id "
            "FROM app.api_tokens t"
        )
    ).all()

    bootstrap = _pick_bootstrap_tenant(bind)
    revoked = 0
    for row in rows:
        token_id = row[0]
        tenant_id = row[2]
        if tenant_id is None:
            if bootstrap is None:
                raise RuntimeError(
                    "phase31: orphan api_token with no owner membership and "
                    "no bootstrap tenant available — cannot backfill safely. "
                    "Provision a tenant first or DELETE the orphan rows."
                )
            bind.execute(
                sa.text(
                    "UPDATE app.api_tokens "
                    "SET tenant_id = :tid, revoked_at = COALESCE(revoked_at, now()) "
                    "WHERE id = :id"
                ),
                {"tid": bootstrap, "id": token_id},
            )
            revoked += 1
        else:
            bind.execute(
                sa.text(
                    "UPDATE app.api_tokens SET tenant_id = :tid WHERE id = :id"
                ),
                {"tid": tenant_id, "id": token_id},
            )
    if revoked:
        logger.warning(
            "phase31: revoked %s api_tokens whose owner has no 'owner' "
            "tenant membership (bound to bootstrap tenant for FK).",
            revoked,
        )


def _backfill_integrations(bind: Any) -> None:
    """Populate ``integrations.tenant_id`` to the bootstrap tenant.

    Integrations are global today (no user_id, no tenant_id). We can only
    safely attribute them to a single workspace. If no tenant exists we
    refuse rather than guess.
    """

    count_row = bind.execute(
        sa.text("SELECT COUNT(*) FROM app.integrations")
    ).first()
    if count_row is None or count_row[0] == 0:
        return
    bootstrap = _pick_bootstrap_tenant(bind)
    if bootstrap is None:
        raise RuntimeError(
            "phase31: app.integrations is non-empty but app.tenants is empty. "
            "Provision the bootstrap tenant (slug='cozy-downloads-store') "
            "before applying this migration."
        )
    bind.execute(
        sa.text("UPDATE app.integrations SET tenant_id = :tid"),
        {"tid": bootstrap},
    )
    logger.info(
        "phase31: backfilled %s integrations rows to tenant %s",
        count_row[0],
        bootstrap,
    )


# ─── Entry points ────────────────────────────────────────────────────────────


def upgrade() -> None:
    _create_documents()
    _create_document_links()

    # api_tokens.tenant_id — add as nullable, backfill, then set NOT NULL.
    op.add_column(
        "api_tokens",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        "fk_app_api_tokens_tenant",
        "api_tokens",
        "tenants",
        ["tenant_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )

    bind = op.get_bind()
    _backfill_api_tokens(bind)

    op.alter_column(
        "api_tokens",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="app",
    )
    op.create_index(
        "ix_app_api_tokens_tenant_id",
        "api_tokens",
        ["tenant_id"],
        schema="app",
    )

    # integrations.tenant_id — same staged add/backfill/NOT NULL pattern.
    op.add_column(
        "integrations",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        schema="app",
    )
    op.create_foreign_key(
        "fk_app_integrations_tenant",
        "integrations",
        "tenants",
        ["tenant_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )

    _backfill_integrations(bind)

    op.alter_column(
        "integrations",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="app",
    )
    op.create_index(
        "ix_app_integrations_tenant_id",
        "integrations",
        ["tenant_id"],
        schema="app",
    )

    logger.info("phase31: schema and backfill complete")


def downgrade() -> None:
    op.drop_index(
        "ix_app_integrations_tenant_id", "integrations", schema="app"
    )
    op.drop_constraint(
        "fk_app_integrations_tenant",
        "integrations",
        schema="app",
        type_="foreignkey",
    )
    op.drop_column("integrations", "tenant_id", schema="app")

    op.drop_index(
        "ix_app_api_tokens_tenant_id", "api_tokens", schema="app"
    )
    op.drop_constraint(
        "fk_app_api_tokens_tenant",
        "api_tokens",
        schema="app",
        type_="foreignkey",
    )
    op.drop_column("api_tokens", "tenant_id", schema="app")

    op.drop_index(
        "ix_app_document_links_dst_target", "document_links", schema="app"
    )
    op.drop_index(
        "ix_app_document_links_tenant_dst",
        "document_links",
        schema="app",
    )
    op.drop_table("document_links", schema="app")

    op.drop_index(
        "ix_app_documents_tenant_archived", "documents", schema="app"
    )
    op.drop_index(
        "ix_app_documents_tenant_id", "documents", schema="app"
    )
    op.drop_table("documents", schema="app")
