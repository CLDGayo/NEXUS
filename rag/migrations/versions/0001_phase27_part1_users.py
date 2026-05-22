"""Phase 27 Part 1 — IAM foundation tables.

Revision ID: 0001_phase27_part1_users
Revises:
Create Date: 2026-05-22

Creates the three ``app`` schema tables that fastapi-users + the chat
session ownership model depend on:

* ``app.users`` — fastapi-users default columns + ``display_name`` +
  ``profile_image_url`` + ``created_at``.
* ``app.access_token`` — reserved for fastapi-users' future
  ``DatabaseStrategy`` swap; unused while ``JWTStrategy`` is the backend.
* ``app.chat_sessions`` — server-issued session_id with FK to users.id.
  Every chat turn validates ownership against this table before invoking
  LangGraph (which keeps using the bare session_id as its thread_id).

The ``app`` schema is created up-front by ``infra/postgres/init.sql`` on
fresh Postgres containers; we still ``CREATE SCHEMA IF NOT EXISTS`` here
so a hand-rolled DB (e.g. a managed Postgres) gets it without operator
intervention.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_phase27_part1_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("profile_image_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_app_users_email", "users", ["email"], unique=True, schema="app"
    )

    op.create_table(
        "access_token",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=43), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token"),
        schema="app",
    )
    op.create_index(
        "ix_app_access_token_created_at",
        "access_token",
        ["created_at"],
        unique=False,
        schema="app",
    )

    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id"),
        schema="app",
    )
    op.create_index(
        "ix_app_chat_sessions_user_id",
        "chat_sessions",
        ["user_id"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_chat_sessions_user_id", table_name="chat_sessions", schema="app"
    )
    op.drop_table("chat_sessions", schema="app")
    op.drop_index(
        "ix_app_access_token_created_at", table_name="access_token", schema="app"
    )
    op.drop_table("access_token", schema="app")
    op.drop_index("ix_app_users_email", table_name="users", schema="app")
    op.drop_table("users", schema="app")
