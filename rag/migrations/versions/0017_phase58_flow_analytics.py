"""Phase 58.4a — flow_runs analytics instrumentation.

Adds two columns to ``app.flow_runs`` so per-node visit + failure counts can
be aggregated without a dedicated events table:
    * ``path`` (JSONB list) — ordered trail of visited node ids, appended in
      ``_traverse`` during execution.
    * ``failed_node_id`` (String) — the node that drove ``status='failed'``.

Both are backfill-safe (server defaults / nullable) so existing rows upgrade
cleanly.

Revision ID: 0017_phase58_flow_analytics
Revises: 0016_phase58_flow_contacts
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_phase58_flow_analytics"
down_revision = "0016_phase58_flow_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column(
            "path",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="app",
    )
    op.add_column(
        "flow_runs",
        sa.Column("failed_node_id", sa.String(64), nullable=True),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("flow_runs", "failed_node_id", schema="app")
    op.drop_column("flow_runs", "path", schema="app")
