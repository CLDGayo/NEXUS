"""Phase 64 — Smart Delay temporal execution for NEXUS Flow.

Adds:
    * ``app.flow_runs.resume_at`` (TIMESTAMPTZ, nullable) — when a ``smartDelay``
      node halts traversal, this holds the wall-clock time the background poller
      should resume the run from ``current_node_id``.
    * Extends ``ck_flow_run_status`` with the new ``'sleeping'`` state.
    * Partial index ``ix_flow_runs_due`` on ``resume_at WHERE status='sleeping'``
      so the poller's "due runs" scan stays cheap as completed/failed rows pile up.

Revision ID: 0021_phase64_smart_delay
Revises: 0020_phase67_live_chat_inbox
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_phase64_smart_delay"
down_revision = "0020_phase67_live_chat_inbox"
branch_labels = None
depends_on = None

_OLD_STATUS = "status IN ('active','waiting','completed','failed')"
_NEW_STATUS = "status IN ('active','waiting','sleeping','completed','failed')"


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("resume_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.drop_constraint("ck_flow_run_status", "flow_runs", schema="app")
    op.create_check_constraint(
        "ck_flow_run_status", "flow_runs", _NEW_STATUS, schema="app"
    )
    op.create_index(
        "ix_flow_runs_due",
        "flow_runs",
        ["resume_at"],
        schema="app",
        postgresql_where=sa.text("status = 'sleeping'"),
    )


def downgrade() -> None:
    op.drop_index("ix_flow_runs_due", table_name="flow_runs", schema="app")
    op.drop_constraint("ck_flow_run_status", "flow_runs", schema="app")
    op.create_check_constraint(
        "ck_flow_run_status", "flow_runs", _OLD_STATUS, schema="app"
    )
    op.drop_column("flow_runs", "resume_at", schema="app")
