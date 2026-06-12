"""Phase 51 — Invitations & Onboarding: tenant_invites table.

Adds ``app.tenant_invites`` — one row per outstanding invite (email-targeted
or open join-code). The raw token is returned once at creation; only the
SHA-256 hash is persisted.

Revision ID: 0009_phase51_invites
Revises: 0008_phase50_rbac_admin
Create Date: 2026-06-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_phase51_invites"
down_revision = "0008_phase50_rbac_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_invites",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_tenant_invites_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name="ck_tenant_invites_status",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("tenant_invites", schema="app")
