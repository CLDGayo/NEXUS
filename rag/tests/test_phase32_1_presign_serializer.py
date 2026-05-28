"""Phase 32.1 — image_url serializer presigns when no CDN is configured.

Regression guard for Bugs 2 + 3: before the hotfix, ``_serialize_image``
called ``public_url_for`` exclusively, which returns ``None`` whenever
``MINIO_PUBLIC_BASE_URL`` is empty. The SPA then bound ``<img src={null}>``
and rendered the broken-file icon (list view) or stayed on the grey
"loading..." placeholder (carousel editor) forever.

This test pins the new behavior: when no CDN URL is available, the
serializer falls back to a presigned MinIO GET URL so the browser can
render the image.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

from rag.routers import products as products_module


def _fake_image(storage_key: str = "tenant/abc/img.webp") -> Any:
    return SimpleNamespace(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        storage_key=storage_key,
        display_order=0,
        width=200,
        height=200,
        content_type="image/webp",
    )


def test_serialize_image_uses_cdn_when_configured(monkeypatch) -> None:
    """When public_url_for returns a CDN URL, presigning is skipped."""
    monkeypatch.setattr(
        products_module.object_store,
        "public_url_for",
        lambda key, *, bucket=None: f"https://cdn.example.com/{bucket}/{key}",
    )

    async def _explode(*_a: Any, **_kw: Any) -> str:
        raise AssertionError("presigned_get_url must not be called when CDN URL is available")

    monkeypatch.setattr(products_module.object_store, "presigned_get_url", _explode)

    img = _fake_image()
    out = asyncio.run(products_module._serialize_image(img))
    assert out.image_url == "https://cdn.example.com/None/tenant/abc/img.webp" or out.image_url.startswith(
        "https://cdn.example.com/"
    )


def test_serialize_image_falls_back_to_object_proxy(monkeypatch) -> None:
    """Phase 32.2 — when public_url_for returns None, the serializer hands
    back a ``/api/objects/<token>`` URL (the bytes-through-api proxy) rather
    than a presigned MinIO URL. Production MinIO is internal-only, so any
    presigned URL embeds an unreachable hostname; the proxy keeps the
    request on the SPA's origin."""
    monkeypatch.setattr(
        products_module.object_store,
        "public_url_for",
        lambda key, *, bucket=None: None,
    )

    img = _fake_image()
    out = asyncio.run(products_module._serialize_image(img))

    assert out.image_url is not None
    assert out.image_url.startswith("/api/objects/"), (
        "must be a same-origin proxy URL; presigned-to-internal-host was the 32.1 bug"
    )

    # Token round-trips back to the original bucket + key.
    from rag.services import object_proxy
    token = out.image_url[len("/api/objects/"):]
    bucket, key = object_proxy.decode_token(token)
    assert bucket == products_module.settings.minio_bucket_products
    assert key == "tenant/abc/img.webp"
