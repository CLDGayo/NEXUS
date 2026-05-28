"""Phase 32 — orchestrator product-carousel branch unit tests.

Phase 32.5 — the single ``enrich_with_products_node`` is split into
``inject_product_context_node`` (pre-generate, all surfaces) and
``build_carousel_node`` (post-respond, messenger only). Tests for the
new nodes live in ``test_phase32_5_product_context_injection.py``;
this file keeps coverage for the pure helpers (``_truncate``,
``_format_price``, ``_ctx_url_for``, ``_image_url_for``).
"""

from __future__ import annotations

import asyncio

import pytest

from rag.orchestrator import product_branch


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


# ---- Phase 32.4 — Messenger-fetchable image_url ----


def _stub_image(image_url: str | None = None, storage_key: str | None = "k.webp"):
    from types import SimpleNamespace

    return SimpleNamespace(image_url=image_url, storage_key=storage_key)


def test_image_url_returns_cdn_when_image_url_set() -> None:
    """Cached absolute CDN URL short-circuits the proxy path."""
    image = _stub_image(image_url="https://cdn.example.com/x.webp")
    result = asyncio.run(product_branch._image_url_for(image))
    assert result == "https://cdn.example.com/x.webp"


def test_image_url_uses_object_proxy_when_nexus_public_base_url_set(
    monkeypatch,
) -> None:
    """Cache miss + public base set → absolute SPA-proxy URL."""
    from rag.config import settings as cfg
    from rag.services import object_proxy

    monkeypatch.setattr(
        cfg, "nexus_public_base_url", "https://chat.nexus.gayo-sphere.cloud"
    )
    monkeypatch.setattr(object_proxy, "proxy_url", lambda **_kw: "/api/objects/SIGNED")

    image = _stub_image(image_url=None, storage_key="products/x.webp")
    result = asyncio.run(product_branch._image_url_for(image))
    assert result == "https://chat.nexus.gayo-sphere.cloud/api/objects/SIGNED"


def test_image_url_strips_trailing_slash_on_base(monkeypatch) -> None:
    """Base with trailing slash must not produce a double slash."""
    from rag.config import settings as cfg
    from rag.services import object_proxy

    monkeypatch.setattr(
        cfg, "nexus_public_base_url", "https://chat.nexus.gayo-sphere.cloud/"
    )
    monkeypatch.setattr(object_proxy, "proxy_url", lambda **_kw: "/api/objects/TOK")

    image = _stub_image(image_url=None)
    result = asyncio.run(product_branch._image_url_for(image))
    assert result == "https://chat.nexus.gayo-sphere.cloud/api/objects/TOK"


def test_image_url_returns_none_when_no_public_base_and_no_cdn(
    monkeypatch,
) -> None:
    """No CDN URL, no NEXUS_PUBLIC_BASE_URL → drop the image (None)."""
    from rag.config import settings as cfg

    monkeypatch.setattr(cfg, "nexus_public_base_url", "")
    monkeypatch.setattr(cfg, "minio_public_base_url", "")

    image = _stub_image(image_url=None)
    result = asyncio.run(product_branch._image_url_for(image))
    assert result is None


def test_image_url_returns_none_when_storage_key_missing() -> None:
    image = _stub_image(image_url=None, storage_key=None)
    result = asyncio.run(product_branch._image_url_for(image))
    assert result is None


def test_image_url_returns_none_when_proxy_url_raises(monkeypatch) -> None:
    """Defensive: object_proxy failure must not raise into the webhook."""
    from rag.config import settings as cfg
    from rag.services import object_proxy

    monkeypatch.setattr(cfg, "nexus_public_base_url", "https://x.example.com")

    def boom(**_kw):
        raise ValueError("synthetic")

    monkeypatch.setattr(object_proxy, "proxy_url", boom)
    image = _stub_image(image_url=None)
    result = asyncio.run(product_branch._image_url_for(image))
    assert result is None
