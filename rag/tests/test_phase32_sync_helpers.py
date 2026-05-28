"""Phase 32 — hybrid-sync helpers: deterministic point id + payload shape.

Pure-unit tests on rag.products.sync. No Qdrant client constructed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from rag.products import sync as sync_module


def test_product_point_id_is_deterministic_per_uuid() -> None:
    pid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    a = sync_module.product_point_id(pid)
    b = sync_module.product_point_id(pid)
    assert a == b
    # Sanity: it's a valid UUID string (uuid5 output).
    assert uuid.UUID(a).version == 5


def test_product_point_id_collisions_across_products_are_impossible() -> None:
    a = sync_module.product_point_id(uuid.uuid4())
    b = sync_module.product_point_id(uuid.uuid4())
    assert a != b


def test_payload_carries_required_fields() -> None:
    product = SimpleNamespace(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        name="Glow Serum 30ml",
        slug="glow-serum-30ml",
        description="Brightens skin overnight",
        price_cents=4500,
        currency="USD",
        is_active=True,
        quantity=12,
        url="https://shop.example.com/p/glow",
    )
    payload = sync_module._payload(product, tenant_slug="hunter")
    assert payload["kind"] == "product"
    assert payload["product_id"] == str(product.id)
    assert payload["tenant_id"] == "hunter"
    assert payload["price_cents"] == 4500
    assert payload["currency"] == "USD"
    assert payload["is_active"] is True
    assert payload["quantity"] == 12
    assert payload["url"] == "https://shop.example.com/p/glow"
    assert payload["name"] == "Glow Serum 30ml"


def test_embed_document_combines_name_and_description(monkeypatch) -> None:
    captured: list[str] = []

    def fake_embed(text: str) -> list[float]:
        captured.append(text)
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(sync_module, "embed_text", fake_embed)
    product = SimpleNamespace(
        id=uuid.uuid4(),
        name="Glow Serum",
        description="Vitamin C boost",
        price_cents=0,
        currency="USD",
        is_active=True,
        quantity=1,
        url=None,
    )
    sync_module._embed_document(product)
    assert captured == ["Glow Serum\n\nVitamin C boost"]


def test_embed_document_falls_back_to_name_only(monkeypatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        sync_module,
        "embed_text",
        lambda t: captured.append(t) or [0.0],
    )
    product = SimpleNamespace(
        id=uuid.uuid4(),
        name="Glow Serum",
        description="",
        price_cents=0,
        currency="USD",
        is_active=True,
        quantity=1,
        url=None,
    )
    sync_module._embed_document(product)
    assert captured == ["Glow Serum"]
