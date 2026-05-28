"""Phase 29 — Strict multi-tenancy foundation.

Revision ID: 0002_phase29_multi_tenancy
Revises: 0001_phase27_part1_users
Create Date: 2026-05-25

Adds the three pillars of strict tenancy:

* ``app.tenants`` — workspace boundary. Seeded with a default ``Hunter``
  tenant (fixed UUID, slug ``hunter``) so existing rows have somewhere to
  land before the NOT NULL constraint lands.
* ``app.tenant_users`` — composite-PK membership table with a ``role``
  column (``owner`` | ``member``). Every existing user is bound to the
  Hunter tenant as ``owner`` on upgrade.
* ``app.chat_sessions.tenant_id`` — added NULLABLE first, backfilled to the
  Hunter tenant id for all existing rows, then promoted to NOT NULL with
  a covering index.

The fixed UUID literal ``DEFAULT_TENANT_ID`` is hardcoded so reruns and
tests agree — the value must NEVER change once any data has been ingested
against it; ingestion writes the slug, not the UUID, to Qdrant payloads,
but the FK on ``chat_sessions`` does point at the UUID and a regenerated
literal would orphan every backfilled row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_phase29_multi_tenancy"
down_revision = "0001_phase27_part1_users"
branch_labels = None
depends_on = None


# Fixed UUID for the default "Hunter" tenant. Generated once for Phase 29
# and frozen for the lifetime of the deployment.
DEFAULT_TENANT_ID = "4e15a5c0-7b9f-4f8e-9e30-1d000000beef"
DEFAULT_TENANT_NAME = "Cozy Downloads Store"
DEFAULT_TENANT_SLUG = "cozy-downloads-store"


def upgrade() -> None:
    # 1. tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        schema="app",
    )
    op.create_index(
        "ix_app_tenants_slug",
        "tenants",
        ["slug"],
        unique=True,
        schema="app",
    )

    # 2. tenant_users join table (composite PK)
    op.create_table(
        "tenant_users",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'owner'"),
        ),
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
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
        schema="app",
    )

    # 3. chat_sessions.tenant_id — add NULLABLE for backfill
    op.add_column(
        "chat_sessions",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        schema="app",
    )

    # 4. Seed default Hunter tenant + bind every existing user + backfill
    #    every existing chat session row. ON CONFLICT clauses keep the
    #    migration idempotent across reruns.
    op.execute(
        sa.text(
            """
            INSERT INTO app.tenants (id, name, slug, created_at)
            VALUES (CAST(:tid AS uuid), :name, :slug, NOW())
            ON CONFLICT (slug) DO NOTHING
            """
        ).bindparams(
            tid=DEFAULT_TENANT_ID,
            name=DEFAULT_TENANT_NAME,
            slug=DEFAULT_TENANT_SLUG,
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO app.tenant_users (tenant_id, user_id, role, created_at)
            SELECT CAST(:tid AS uuid), id, 'owner', NOW() FROM app.users
            ON CONFLICT (tenant_id, user_id) DO NOTHING
            """
        ).bindparams(tid=DEFAULT_TENANT_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE app.chat_sessions
            SET tenant_id = CAST(:tid AS uuid)
            WHERE tenant_id IS NULL
            """
        ).bindparams(tid=DEFAULT_TENANT_ID)
    )

    # 5. Promote tenant_id to NOT NULL + add FK + covering index
    op.alter_column(
        "chat_sessions",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="app",
    )
    op.create_foreign_key(
        "fk_chat_sessions_tenant_id",
        "chat_sessions",
        "tenants",
        ["tenant_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_app_chat_sessions_tenant_id",
        "chat_sessions",
        ["tenant_id"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_chat_sessions_tenant_id",
        table_name="chat_sessions",
        schema="app",
    )
    op.drop_constraint(
        "fk_chat_sessions_tenant_id",
        "chat_sessions",
        type_="foreignkey",
        schema="app",
    )
    op.drop_column("chat_sessions", "tenant_id", schema="app")
    op.drop_table("tenant_users", schema="app")
    op.drop_index(
        "ix_app_tenants_slug", table_name="tenants", schema="app"
    )
    op.drop_table("tenants", schema="app")
