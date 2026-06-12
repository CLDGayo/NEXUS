"""Phase 52 — Workspace Lifecycle & Danger Zone: add avatar_url + archived_at to tenants.

Revision ID: 0010_phase52_wm3_lifecycle
Revises: 0009_phase51_invites
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_phase52_wm3_lifecycle"
down_revision = "0009_phase51_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("avatar_url", sa.String(500), nullable=True),
        schema="app",
    )
    op.add_column(
        "tenants",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("tenants", "archived_at", schema="app")
    op.drop_column("tenants", "avatar_url", schema="app")
