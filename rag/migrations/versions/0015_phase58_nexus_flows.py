"""Phase 58 — NEXUS Flow visual automation engine.

Adds:
    * ``app.nexus_flows``  — canvas definition (nodes/edges JSONB + is_active flag)
    * ``app.flow_runs``    — per-user execution state (current_node_id, status, context)

Revision ID: 0015_phase58_nexus_flows
Revises: 0014_phase57_comment_to_message
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_phase58_nexus_flows"
down_revision = "0014_phase57_comment_to_message"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- nexus_flows ---
    op.create_table(
        "nexus_flows",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "flow_state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        schema="app",
    )
    op.create_index(
        "ix_nexus_flows_tenant",
        "nexus_flows",
        ["tenant_id"],
        schema="app",
    )
    # Partial index — only active flows matter for the webhook lookup.
    op.create_index(
        "ix_nexus_flows_page_active",
        "nexus_flows",
        ["page_id"],
        schema="app",
        postgresql_where=sa.text("is_active"),
    )

    # --- flow_runs ---
    op.create_table(
        "flow_runs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.nexus_flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column("sender_id", sa.String(128), nullable=False),
        sa.Column("current_node_id", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.CheckConstraint(
            "status IN ('active','waiting','completed','failed')",
            name="ck_flow_run_status",
        ),
        schema="app",
    )
    # Partial unique index: one live run per user per page.
    op.create_index(
        "uq_flow_run_live",
        "flow_runs",
        ["page_id", "sender_id"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status IN ('active','waiting')"),
    )
    op.create_index(
        "ix_flow_runs_resume",
        "flow_runs",
        ["page_id", "sender_id", "status"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_flow_runs_resume", table_name="flow_runs", schema="app")
    op.drop_index("uq_flow_run_live", table_name="flow_runs", schema="app")
    op.drop_table("flow_runs", schema="app")
    op.drop_index("ix_nexus_flows_page_active", table_name="nexus_flows", schema="app")
    op.drop_index("ix_nexus_flows_tenant", table_name="nexus_flows", schema="app")
    op.drop_table("nexus_flows", schema="app")
