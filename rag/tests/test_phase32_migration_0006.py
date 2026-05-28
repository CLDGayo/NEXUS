"""Phase 32 — migration 0006 module guards.

Verifies the new revision is wired to follow Phase 31 and that both
``upgrade`` and ``downgrade`` exist + the new ORM mappers register without
import-time errors.
"""

from __future__ import annotations

import importlib


def test_revision_chain() -> None:
    module = importlib.import_module(
        "rag.migrations.versions.0006_phase32_products"
    )
    assert module.revision == "0006_phase32_products"
    assert module.down_revision == "0005_phase31_security_and_docs"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_product_models_register() -> None:
    """ORM import must not raise (relationship + FK strings resolve)."""
    from rag.database import models

    assert hasattr(models, "Product")
    assert hasattr(models, "ProductImage")
    assert models.Product.__tablename__ == "products"
    assert models.ProductImage.__tablename__ == "product_images"


def test_product_unique_and_check_constraints_declared() -> None:
    from rag.database.models import Product

    names = {c.name for c in Product.__table_args__ if hasattr(c, "name")}
    assert "uq_app_products_tenant_slug" in names
    assert "ck_app_products_price_nonneg" in names
    assert "ck_app_products_qty_nonneg" in names


def test_product_image_unique_order_constraint_declared() -> None:
    from rag.database.models import ProductImage

    names = {c.name for c in ProductImage.__table_args__ if hasattr(c, "name")}
    assert "uq_app_product_images_order" in names
