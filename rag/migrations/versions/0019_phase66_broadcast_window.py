"""Phase 66 — broadcast messaging-window anchor on flow_contacts.

Adds ``last_interaction_at`` (nullable TIMESTAMPTZ) to ``app.flow_contacts``.
This column records the last inbound *Messenger message* timestamp per sender
and is the anchor for Meta's 24-hour standard messaging window enforced by the
Audience Broadcasting engine (``rag/messenger/routers/broadcasts.py``).

Backfill-safe: nullable with no server default, so existing rows upgrade with
``NULL`` (treated as "outside the window" → never broadcast to until the sender
messages the page again, which is the conservative / compliant default).

A b-tree index keeps the window filter
(``last_interaction_at >= now() - interval '24 hours'``) index-backed instead of
forcing a sequential scan over every contact for the tenant.

Revision ID: 0019_phase66_broadcast_window
Revises: 0018_phase59_tenant_language
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_phase66_broadcast_window"
down_revision = "0018_phase59_tenant_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_contacts",
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_flow_contacts_last_interaction_at",
        "flow_contacts",
        ["last_interaction_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_flow_contacts_last_interaction_at",
        table_name="flow_contacts",
        schema="app",
    )
    op.drop_column("flow_contacts", "last_interaction_at", schema="app")
