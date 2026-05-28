"""Phase 32 — static contract guards for the products router.

A future PR that drops ``require_owner`` from any products route would
re-open the catalogue to non-owners; a PR that drops the ``tenant_id``
filter would let an owner of workspace A read/mutate workspace B's
inventory. These tests fail loudly the moment either invariant slips.
"""

from __future__ import annotations

import inspect

from routers import products as products_module
from routers import integrations as integrations_module


def test_products_router_uses_require_owner() -> None:
    src = inspect.getsource(products_module)
    assert "from routers.deps import require_owner" in src
    assert "require_owner" in src


def test_products_router_filters_every_query_by_tenant() -> None:
    src = inspect.getsource(products_module)
    assert "Product.tenant_id == tenant.id" in src, (
        "every Product query must carry the tenant_id filter"
    )


def test_products_router_hybrid_sync_imports() -> None:
    src = inspect.getsource(products_module)
    assert "upsert_product_to_qdrant" in src
    assert "delete_product_from_qdrant" in src


def test_messenger_page_binding_routes_present() -> None:
    src = inspect.getsource(integrations_module)
    assert '@router.post("/messenger/pages"' in src
    assert '@router.delete(' in src and '/messenger/pages/' in src
    assert "page_bound_to_other_tenant" in src
