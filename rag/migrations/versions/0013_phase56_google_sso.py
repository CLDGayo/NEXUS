"""Phase 56 — Multi-tenant Google SSO + identity linking.

Adds:
    * ``app.oauth_accounts``      — third-party identity links (encrypted tokens)
    * ``app.oauth_states``        — single-use CSRF state + nonce + PKCE verifier
    * ``app.refresh_tokens``      — rotating refresh tokens (SHA-256 hashed)
    * ``app.domain_join_requests``— pending domain auto-join (admin approval)
    * ``app.tenants.domain``      — domain auto-join key (indexed)
    * functional unique index ``lower(email)`` on ``app.users`` so account
      linking is case-insensitive and race-safe.

Revision ID: 0013_phase56_google_sso
Revises: 0012_phase55_fb_page_sync
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_phase56_google_sso"
down_revision = "0012_phase55_fb_page_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenants.domain + case-insensitive user email guard ---
    op.add_column(
        "tenants",
        sa.Column("domain", sa.String(253), nullable=True),
        schema="app",
    )
    op.create_index("ix_tenants_domain", "tenants", ["domain"], schema="app")
    # Case-insensitive uniqueness so linking by lower(email) cannot race two
    # rows into existence. Guard: fails loudly if duplicate-by-case rows exist.
    op.create_index(
        "uq_users_lower_email",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        schema="app",
    )

    # --- oauth_accounts ---
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("oauth_name", sa.String(100), nullable=False),
        sa.Column("account_id", sa.String(320), nullable=False),
        sa.Column("account_email", sa.String(320), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "oauth_name", "account_id", name="uq_oauth_provider_account"
        ),
        schema="app",
    )

    # --- oauth_states ---
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("invite_token", sa.String(128), nullable=True),
        sa.Column("redirect_after", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )

    # --- refresh_tokens ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="app",
    )

    # --- domain_join_requests ---
    op.create_table(
        "domain_join_requests",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email_domain", sa.String(253), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "decided_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_djr_status",
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_djr_tenant_user"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("domain_join_requests", schema="app")
    op.drop_table("refresh_tokens", schema="app")
    op.drop_table("oauth_states", schema="app")
    op.drop_table("oauth_accounts", schema="app")
    op.drop_index("uq_users_lower_email", "users", schema="app")
    op.drop_index("ix_tenants_domain", "tenants", schema="app")
    op.drop_column("tenants", "domain", schema="app")
