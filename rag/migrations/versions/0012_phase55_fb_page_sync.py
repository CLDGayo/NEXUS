"""Phase 55 — Facebook Page metadata sync.

Extends ``app.messenger_page_tenants`` with page metadata + an encrypted
per-page access token + sync/token status, and adds the per-tenant
``app.facebook_user_tokens`` table holding the long-lived (~60d) user token.

Revision ID: 0012_phase55_fb_page_sync
Revises: 0011_phase54_user_language
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_phase55_fb_page_sync"
down_revision = "0011_phase54_user_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messenger_page_tenants",
        sa.Column("page_name", sa.String(256), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("page_about", sa.Text(), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("profile_picture_url", sa.String(1024), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("page_access_token_enc", sa.Text(), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column(
            "token_status", sa.String(16), nullable=False, server_default="active"
        ),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("subscribed_fields", postgresql.JSONB(), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column("sync_status", sa.String(16), nullable=False, server_default="ok"),
        schema="app",
    )
    op.add_column(
        "messenger_page_tenants",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="app",
    )
    op.create_check_constraint(
        "ck_mpt_token_status",
        "messenger_page_tenants",
        "token_status IN ('active', 'expired', 'revoked', 'invalid')",
        schema="app",
    )
    op.create_check_constraint(
        "ck_mpt_sync_status",
        "messenger_page_tenants",
        "sync_status IN ('ok', 'stale', 'error')",
        schema="app",
    )

    op.create_table(
        "facebook_user_tokens",
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fb_user_id", sa.String(64), nullable=False),
        sa.Column("user_token_enc", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=True),
        sa.Column(
            "token_status", sa.String(16), nullable=False, server_default="active"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "token_status IN ('active', 'expired', 'revoked', 'invalid')",
            name="ck_fut_token_status",
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("facebook_user_tokens", schema="app")
    op.drop_constraint(
        "ck_mpt_sync_status", "messenger_page_tenants", schema="app", type_="check"
    )
    op.drop_constraint(
        "ck_mpt_token_status", "messenger_page_tenants", schema="app", type_="check"
    )
    for col in (
        "updated_at",
        "sync_status",
        "last_synced_at",
        "subscribed_fields",
        "token_expires_at",
        "token_status",
        "page_access_token_enc",
        "profile_picture_url",
        "page_about",
        "page_name",
    ):
        op.drop_column("messenger_page_tenants", col, schema="app")
