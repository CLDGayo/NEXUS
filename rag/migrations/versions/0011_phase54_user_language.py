"""Phase 54 — per-user UI language preference: add language to users.

Revision ID: 0011_phase54_user_language
Revises: 0010_phase52_wm3_lifecycle
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_phase54_user_language"
down_revision = "0010_phase52_wm3_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default backfills existing rows to English; the column stays NOT
    # NULL so reads never have to special-case a missing preference.
    op.add_column(
        "users",
        sa.Column(
            "language",
            sa.String(8),
            nullable=False,
            server_default="en",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("users", "language", schema="app")
