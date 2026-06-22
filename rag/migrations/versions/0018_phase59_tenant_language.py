"""Phase 59 — workspace default chatbot language: add preferred_language to tenants.

Revision ID: 0018_phase59_tenant_language
Revises: 0017_phase58_flow_analytics
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_phase59_tenant_language"
down_revision = "0017_phase58_flow_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default backfills existing rows to English; the column stays NOT
    # NULL so the flow engine never has to special-case a missing preference.
    op.add_column(
        "tenants",
        sa.Column(
            "preferred_language",
            sa.String(8),
            nullable=False,
            server_default="en",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("tenants", "preferred_language", schema="app")
