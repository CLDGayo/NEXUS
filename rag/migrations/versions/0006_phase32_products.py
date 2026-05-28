"""Phase 32 — Product catalog + image registry.

Revision ID: 0006_phase32_products
Revises: 0005_phase31_security_and_docs
Create Date: 2026-05-28

Adds the tenant-scoped product catalog that backs the E-Commerce AI:

    * ``app.products`` — one row per merchant SKU. UNIQUE (tenant_id, slug)
      keeps the URL-friendly handle disambiguated inside a workspace
      without cross-tenant collision.
    * ``app.product_images`` — ordered image attachments. UNIQUE
      (product_id, display_order) enforces gap-free carousel ordering;
      the router uses a negative-offset swap inside a transaction to
      reassign positions safely under concurrent edits.

No backfill — greenfield tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_phase32_products"
down_revision = "0005_phase31_security_and_docs"
branch_labels = None
depends_on = None


def _create_products() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "price_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "extra_metadata",
            sa.dialects.postgresql.JSONB(),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["app.tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "slug", name="uq_app_products_tenant_slug"
        ),
        sa.CheckConstraint("price_cents >= 0", name="ck_app_products_price_nonneg"),
        sa.CheckConstraint("quantity >= 0", name="ck_app_products_qty_nonneg"),
        schema="app",
    )
    op.create_index(
        "ix_app_products_tenant_id",
        "products",
        ["tenant_id"],
        schema="app",
    )
    op.create_index(
        "ix_app_products_tenant_carousel",
        "products",
        ["tenant_id", "is_active", "quantity"],
        schema="app",
    )


def _create_product_images() -> None:
    op.create_table(
        "product_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "display_order",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "content_type",
            sa.String(length=64),
            nullable=False,
            server_default="image/webp",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["app.products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "display_order",
            name="uq_app_product_images_order",
        ),
        schema="app",
    )
    op.create_index(
        "ix_app_product_images_product_id",
        "product_images",
        ["product_id"],
        schema="app",
    )


def upgrade() -> None:
    _create_products()
    _create_product_images()


def downgrade() -> None:
    op.drop_index(
        "ix_app_product_images_product_id",
        "product_images",
        schema="app",
    )
    op.drop_table("product_images", schema="app")

    op.drop_index(
        "ix_app_products_tenant_carousel", "products", schema="app"
    )
    op.drop_index("ix_app_products_tenant_id", "products", schema="app")
    op.drop_table("products", schema="app")
