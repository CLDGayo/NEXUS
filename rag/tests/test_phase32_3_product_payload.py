"""Phase 32.3 — product Qdrant payload carries document-compatible keys.

The Documents UI and citation renderer scroll Qdrant grouping by ``file``
and rendering ``title``. Phase 32 shipped products without those keys, so
products were invisible to ``_qdrant_index_summary`` (stayed "Pending") and
citation rendering fell back to raw point UUIDs. These tests pin the
enriched payload contract so any regression flips a red test before it
flips the UI.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from rag.products import sync as sync_module


def _make_product(
    *,
    slug: str = "luffy-gear-4-bound-man",
    description: str = "Anime PVC figure, hand-painted.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        name="Luffy Gear 4 Bound man",
        slug=slug,
        description=description,
        price_cents=210000,
        currency="JPY",
        is_active=True,
        quantity=2,
        url=None,
    )


def test_payload_contains_document_compatible_keys() -> None:
    payload = sync_module._payload(_make_product(), tenant_slug="cozy-downloads")

    assert payload["file"] == "/products/luffy-gear-4-bound-man"
    assert payload["title"] == "Luffy Gear 4 Bound man"
    assert payload["folder"] == "/products"
    assert payload["source_kind"] == "product"
    assert payload["heading_path"] == ["Luffy Gear 4 Bound man"]


def test_payload_text_includes_name_and_description() -> None:
    payload = sync_module._payload(_make_product(), tenant_slug="cozy-downloads")
    assert (
        payload["text"] == "Luffy Gear 4 Bound man\n\nAnime PVC figure, hand-painted."
    )


def test_payload_text_falls_back_to_name_when_description_blank() -> None:
    payload = sync_module._payload(
        _make_product(description=""), tenant_slug="cozy-downloads"
    )
    assert payload["text"] == "Luffy Gear 4 Bound man"


def test_payload_text_falls_back_to_name_when_description_whitespace() -> None:
    payload = sync_module._payload(
        _make_product(description="   \n\t  "), tenant_slug="cozy-downloads"
    )
    assert payload["text"] == "Luffy Gear 4 Bound man"


def test_payload_preserves_existing_phase32_keys() -> None:
    """Document-compat additions must not displace carousel filter fields."""
    payload = sync_module._payload(_make_product(), tenant_slug="cozy-downloads")

    assert payload["kind"] == "product"
    assert payload["product_id"] == "11111111-2222-3333-4444-555555555555"
    assert payload["tenant_id"] == "cozy-downloads"
    assert payload["name"] == "Luffy Gear 4 Bound man"
    assert payload["price_cents"] == 210000
    assert payload["currency"] == "JPY"
    assert payload["is_active"] is True
    assert payload["quantity"] == 2
    assert payload["url"] is None


def test_payload_file_path_matches_documents_router_synth_path() -> None:
    """The synthetic path here must equal the one ``_product_to_doc_dict``
    builds in ``rag/routers/documents.py`` so the SPA's ``indexSummary[path]``
    lookup hits."""

    payload = sync_module._payload(
        _make_product(slug="glow-serum-30ml"), tenant_slug="hunter"
    )
    assert payload["file"] == "/products/glow-serum-30ml"
