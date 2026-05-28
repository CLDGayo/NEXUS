"""Phase 29.2 — Messenger page → tenant mapping.

Revision ID: 0003_phase29_messenger_page_tenants
Revises: 0002_phase29_multi_tenancy
Create Date: 2026-05-27

Adds ``app.messenger_page_tenants`` so the Phase 12 direct webhook can
resolve an inbound Meta page id to its owning tenant before the
LangGraph cortex runs. Unmapped events are dropped at the webhook
boundary (no 5xx — Meta would retry aggressively).

No backfill: empty table on upgrade. Operators seed rows manually (or
via a tiny admin endpoint in a later phase) before pointing a Page at
the deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_phase29_messenger_page_tenants"
down_revision = "0002_phase29_multi_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messenger_page_tenants",
        sa.Column("facebook_page_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("facebook_page_id"),
        schema="app",
    )
    op.create_index(
        "ix_app_messenger_page_tenants_tenant_id",
        "messenger_page_tenants",
        ["tenant_id"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_messenger_page_tenants_tenant_id",
        table_name="messenger_page_tenants",
        schema="app",
    )
    op.drop_table("messenger_page_tenants", schema="app")
