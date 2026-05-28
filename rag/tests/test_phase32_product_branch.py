"""Phase 32 — orchestrator product-carousel branch unit tests.

The branch is messenger-only by design; SPA queries must not pay any
product-search latency. ``_truncate`` / ``_format_price`` are pure
helpers worth covering directly so a future refactor doesn't drift past
Meta's hard limits.
"""

from __future__ import annotations

import asyncio

import pytest

from rag.orchestrator import product_branch


def test_enrich_node_skips_non_messenger_surface(monkeypatch) -> None:
    """SPA surface must not trigger a Qdrant call or DB hit."""
    called = {"qdrant": 0, "enrich": 0}

    async def boom_qdrant(*_args, **_kwargs):  # pragma: no cover
        called["qdrant"] += 1
        return []

    async def boom_enrich(*_args, **_kwargs):  # pragma: no cover
        called["enrich"] += 1
        return []

    monkeypatch.setattr(product_branch, "_candidate_product_ids", boom_qdrant)
    monkeypatch.setattr(product_branch, "_enrich", boom_enrich)

    state = {
        "query": "anything",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "spa",
        "tenant_id": "hunter",
    }
    result = asyncio.run(product_branch.enrich_with_products_node(state))
    assert result == {}
    assert called == {"qdrant": 0, "enrich": 0}


def test_enrich_node_skips_when_no_query() -> None:
    state = {
        "query": "",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "messenger",
        "tenant_id": "hunter",
    }
    result = asyncio.run(product_branch.enrich_with_products_node(state))
    assert result == {}


def test_enrich_node_skips_when_no_tenant() -> None:
    state = {
        "query": "scarf",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "messenger",
    }
    result = asyncio.run(product_branch.enrich_with_products_node(state))
    assert result == {}


def test_enrich_node_empty_when_no_qdrant_candidates(monkeypatch) -> None:
    async def empty_candidates(*_a, **_kw):
        return []

    monkeypatch.setattr(product_branch, "_candidate_product_ids", empty_candidates)
    state = {
        "query": "scarf",
        "thread_key": "tk",
        "correlation_id": "cid",
        "surface": "messenger",
        "tenant_id": "hunter",
    }
    result = asyncio.run(product_branch.enrich_with_products_node(state))
    assert result == {}


def test_truncate_ellipsis_within_limit() -> None:
    out = product_branch._truncate("a" * 100, 20)
    assert len(out) == 20
    assert out.endswith("…")


def test_truncate_short_text_unchanged() -> None:
    assert product_branch._truncate("short", 80) == "short"


def test_format_price_handles_zero_and_locale_safe() -> None:
    assert product_branch._format_price(0, "USD") == "USD 0.00"
    assert product_branch._format_price(4500, "USD") == "USD 45.00"
    assert product_branch._format_price(123456, "PHP").startswith("PHP ")


@pytest.mark.parametrize(
    "url_template, expected_prefix",
    [("", None), ("https://shop.example.com/p/{slug}", "https://shop.example.com/p/")],
)
def test_ctx_url_from_template(url_template, expected_prefix, monkeypatch) -> None:
    from rag.config import settings as cfg

    monkeypatch.setattr(cfg, "product_cta_url_template", url_template)
    from types import SimpleNamespace
    import uuid as _uuid

    product = SimpleNamespace(slug="glow-serum", id=_uuid.uuid4(), url=None)
    result = product_branch._ctx_url_for(product)
    if expected_prefix is None:
        assert result is None
    else:
        assert result is not None and result.startswith(expected_prefix)
