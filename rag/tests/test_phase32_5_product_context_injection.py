"""Phase 32.5 — inject_product_context_node + build_carousel_node split.

The pre-32.5 ``enrich_with_products_node`` ran AFTER ``generate`` and
short-circuited for SPA. That left the LLM blind to live Postgres
product data (price, stock, description), so questions like "how much
is it?" abstained on both surfaces. The new node ``inject_product_context``
runs BEFORE ``generate`` for *all* surfaces and prepends a synthetic
``ScoredChunk`` so the LLM has a citable source for the structured data.

These tests pin:
  1. SPA *and* messenger both trigger context injection.
  2. The synthetic chunk carries the exact ``[Product Catalog Match]``
     prefix the prompt addendum keys off.
  3. Prepended at position 0 so ``_format_context`` numbers it ``[1]``.
  4. Existing reranked chunks remain untouched after the prepend.
  5. Empty query / missing tenant short-circuits with no DB hit.
  6. The cached ``_enriched_products`` state key feeds the carousel
     builder so we don't re-query Postgres downstream.
  7. ``build_carousel_node`` (renamed) stays messenger-gated and reads
     the cached products list.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from rag.orchestrator import product_branch
from rag.retrieval.types import ScoredChunk


def _stub_product(
    *,
    name: str = "Luffy Gear 4 Bound man",
    price_cents: int = 210000,
    currency: str = "JPY",
    quantity: int = 2,
    description: str = "Luffy Boundman",
    pid: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        name=name,
        slug="luffy-gear-4",
        price_cents=price_cents,
        currency=currency,
        quantity=quantity,
        description=description,
        url=None,
        is_active=True,
        images=[],
    )


def _run(coro):
    return asyncio.run(coro)


# ── Surface coverage — both messenger and SPA must inject ──────────────────


def test_inject_node_runs_for_spa_surface(monkeypatch) -> None:
    """SPA was previously skipped. Must now inject so /chat sees the data."""
    product = _stub_product()

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "how much is luffy gear 4?",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    result = _run(product_branch.inject_product_context_node(state))
    assert "reranked" in result
    assert len(result["reranked"]) == 1
    assert "[Product Catalog Match]" in result["reranked"][0].text


def test_inject_node_runs_for_messenger_surface(monkeypatch) -> None:
    product = _stub_product()

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "is this available?",
        "surface": "messenger",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    result = _run(product_branch.inject_product_context_node(state))
    assert len(result["reranked"]) == 1


# ── Synthetic chunk shape — prompt addendum keys off the exact prefix ──────


def test_inject_node_chunk_text_format(monkeypatch) -> None:
    product = _stub_product(
        name="Luffy Gear 4 Bound man",
        price_cents=210000,
        currency="JPY",
        quantity=2,
        description="Luffy Boundman",
    )

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "how much?",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    chunks = _run(product_branch.inject_product_context_node(state))["reranked"]
    text = chunks[0].text
    assert text.startswith("[Product Catalog Match] ")
    assert "Name: Luffy Gear 4 Bound man" in text
    assert "Price: JPY 2,100.00" in text
    assert "Stock: 2 available" in text
    assert "Description: Luffy Boundman" in text


def test_inject_node_handles_empty_description(monkeypatch) -> None:
    """Empty description must not break the format string."""
    product = _stub_product(description="")

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "what is it?",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    chunks = _run(product_branch.inject_product_context_node(state))["reranked"]
    assert "Description: —" in chunks[0].text


def test_inject_node_chunk_metadata(monkeypatch) -> None:
    """Metadata must carry source_kind + product_id for traceability."""
    pid = uuid.uuid4()
    product = _stub_product(pid=pid)

    async def fake_candidates(*_a, **_kw):
        return [pid]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "?",
        "surface": "messenger",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    chunk: ScoredChunk = _run(product_branch.inject_product_context_node(state))[
        "reranked"
    ][0]
    assert chunk.id == f"product:{pid}"
    assert chunk.metadata["source_kind"] == "product_catalog"
    assert chunk.metadata["product_id"] == str(pid)
    assert chunk.metadata["tenant_id"] == "cozy-downloads-store"
    assert chunk.metadata["title"] == "Luffy Gear 4 Bound man"


# ── Ordering — prepend, do not append ──────────────────────────────────────


def test_inject_node_prepends_to_existing_reranked(monkeypatch) -> None:
    """Product chunks must land at [1]; doc chunks slide to [2]+."""
    product = _stub_product()

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    existing = ScoredChunk(id="doc:1", text="some retrieved doc", score=0.5)
    state = {
        "query": "luffy?",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [existing],
    }
    chunks = _run(product_branch.inject_product_context_node(state))["reranked"]
    assert len(chunks) == 2
    assert chunks[0].id.startswith("product:")
    assert chunks[1].id == "doc:1"


# ── Short-circuit paths — no DB hit when not needed ────────────────────────


def test_inject_node_noop_when_no_query() -> None:
    state = {"query": "", "surface": "spa", "tenant_id": "x"}
    assert _run(product_branch.inject_product_context_node(state)) == {}


def test_inject_node_noop_when_no_tenant() -> None:
    state = {"query": "anything", "surface": "spa"}
    assert _run(product_branch.inject_product_context_node(state)) == {}


def test_inject_node_noop_when_no_candidates(monkeypatch) -> None:
    async def empty(*_a, **_kw):
        return []

    monkeypatch.setattr(product_branch, "_candidate_product_ids", empty)
    state = {
        "query": "scarf",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    assert _run(product_branch.inject_product_context_node(state)) == {}


def test_inject_node_noop_when_no_in_stock(monkeypatch) -> None:
    async def some(*_a, **_kw):
        return [uuid.uuid4()]

    async def none(*_a, **_kw):
        return []

    monkeypatch.setattr(product_branch, "_candidate_product_ids", some)
    monkeypatch.setattr(product_branch, "_enrich", none)
    state = {
        "query": "scarf",
        "surface": "spa",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    assert _run(product_branch.inject_product_context_node(state)) == {}


# ── _enriched_products cache key — feeds carousel without re-query ─────────


def test_inject_node_caches_enriched_products(monkeypatch) -> None:
    product = _stub_product()

    async def fake_candidates(*_a, **_kw):
        return [product.id]

    async def fake_enrich(*_a, **_kw):
        return [product]

    monkeypatch.setattr(product_branch, "_candidate_product_ids", fake_candidates)
    monkeypatch.setattr(product_branch, "_enrich", fake_enrich)

    state = {
        "query": "?",
        "surface": "messenger",
        "tenant_id": "cozy-downloads-store",
        "reranked": [],
    }
    result = _run(product_branch.inject_product_context_node(state))
    assert "_enriched_products" in result
    assert len(result["_enriched_products"]) == 1
    assert result["_enriched_products"][0] is product


# ── build_carousel_node — renamed enrich_with_products_node ────────────────


def test_build_carousel_node_skips_non_messenger() -> None:
    state = {"surface": "spa", "_enriched_products": []}
    assert _run(product_branch.build_carousel_node(state)) == {}


def test_build_carousel_node_uses_cached_products(monkeypatch) -> None:
    """Carousel builder must reuse _enriched_products, not re-query."""
    called = {"candidates": 0, "enrich": 0}

    async def boom_candidates(*_a, **_kw):
        called["candidates"] += 1
        return []

    async def boom_enrich(*_a, **_kw):
        called["enrich"] += 1
        return []

    monkeypatch.setattr(product_branch, "_candidate_product_ids", boom_candidates)
    monkeypatch.setattr(product_branch, "_enrich", boom_enrich)

    async def stub_carousel(_products):
        from rag.messenger.payloads import (
            GenericTemplateElement,
            ProductCarouselBlock,
        )

        return ProductCarouselBlock(
            elements=[GenericTemplateElement(title="ok")]
        )

    monkeypatch.setattr(product_branch, "_format_carousel", stub_carousel)

    state = {
        "surface": "messenger",
        "tenant_id": "cozy-downloads-store",
        "_enriched_products": [_stub_product()],
    }
    result = _run(product_branch.build_carousel_node(state))
    assert "product_carousel" in result
    # Critical: cache hit means zero re-queries.
    assert called == {"candidates": 0, "enrich": 0}


def test_build_carousel_node_empty_when_no_cached_products() -> None:
    state = {"surface": "messenger", "tenant_id": "x"}
    assert _run(product_branch.build_carousel_node(state)) == {}
