"""Phase 57 — Facebook Comment-to-Message (Private Reply) engine.

Adds:
    * ``app.facebook_automations``   — keyword rules per page/tenant
    * ``app.processed_fb_comments``  — idempotency lock (comment_id PK)

Revision ID: 0014_phase57_comment_to_message
Revises: 0013_phase56_google_sso
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_phase57_comment_to_message"
down_revision = "0013_phase56_google_sso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- facebook_automations ---
    op.create_table(
        "facebook_automations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("page_id", sa.String(64), nullable=False, index=True),
        sa.Column("trigger_keyword", sa.String(255), nullable=False),
        sa.Column(
            "match_type",
            sa.String(16),
            nullable=False,
            server_default="exact",
        ),
        sa.Column("reply_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "match_type IN ('exact', 'contains')",
            name="ck_fba_match_type",
        ),
        schema="app",
    )
    # Composite index used by the worker's match query.
    op.create_index(
        "ix_facebook_automations_page_active",
        "facebook_automations",
        ["page_id", "is_active"],
        schema="app",
    )

    # --- processed_fb_comments ---
    op.create_table(
        "processed_fb_comments",
        sa.Column("comment_id", sa.String(128), primary_key=True),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_facebook_automations_page_active",
        table_name="facebook_automations",
        schema="app",
    )
    op.drop_table("processed_fb_comments", schema="app")
    op.drop_table("facebook_automations", schema="app")
