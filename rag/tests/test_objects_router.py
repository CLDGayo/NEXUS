"""Phase 32.6 — ``/api/objects/{token}`` HEAD support + GET regression.

Meta's Send API validates ``image_url`` with a HEAD probe before queueing
carousel deliveries. Before Phase 32.6 the route declared only ``GET``,
so HEAD returned 405 and Meta surfaced ``(#100) ... should represent a
valid URL`` — 400-DLQ'ing every carousel send. These tests pin both the
fix (HEAD returns 200 with the right headers and no body) and the GET
regression so the original SPA fetch path keeps working.

The S3 client is mocked at the ``rag.services.object_store.s3_client``
boundary so we don't pay the moto startup cost on every run.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.routers import objects as objects_router
from rag.services import object_proxy


_BUCKET = "nexus-products"
_KEY = "tenant-a/prod-1/img-1.webp"
_CONTENT_TYPE = "image/webp"
_BYTES = b"\x52\x49\x46\x46" + b"\x00" * 28  # 32-byte fake WebP head


class _FakeStreamingBody:
    """Mimic the ``aiobotocore`` StreamingBody surface: an awaitable ``read()``."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _FakeNoSuchKey(Exception):
    """Stand-in for ``client.exceptions.NoSuchKey`` (Pydantic / botocore
    expose this on the live client; tests fabricate it)."""


class _FakeClient:
    """Minimal async S3 client surface used by ``rag.routers.objects``.

    Implements just ``get_object`` and ``head_object``; raises a stand-in
    NoSuchKey on the "missing" key. ``exceptions.NoSuchKey`` is the route
    handler's ``except`` target — we expose it as a class attribute on the
    fake to match botocore's shape.
    """

    exceptions: Any  # populated in __init__

    def __init__(
        self,
        *,
        content_type: str = _CONTENT_TYPE,
        data: bytes = _BYTES,
        missing_keys: set[str] | None = None,
    ) -> None:
        self._content_type = content_type
        self._data = data
        self._missing = missing_keys or set()
        self.head_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[str, str]] = []

        class _Exceptions:
            NoSuchKey = _FakeNoSuchKey

        self.exceptions = _Exceptions()

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.get_calls.append((Bucket, Key))
        if Key in self._missing:
            raise _FakeNoSuchKey()
        return {
            "Body": _FakeStreamingBody(self._data),
            "ContentType": self._content_type,
        }

    async def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.head_calls.append((Bucket, Key))
        if Key in self._missing:
            raise _FakeNoSuchKey()
        return {
            "ContentType": self._content_type,
            "ContentLength": len(self._data),
        }


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    """Override ``object_store.s3_client`` with an async context manager
    yielding ``client``. Avoids moto for this focused router test."""

    @asynccontextmanager
    async def _factory() -> AsyncIterator[_FakeClient]:
        yield client

    monkeypatch.setattr(
        "rag.routers.objects.object_store.s3_client",
        _factory,
        raising=True,
    )


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(objects_router.router, prefix="/api")
    return app


def test_head_returns_200_with_content_type_and_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    _install_fake_client(monkeypatch, fake)
    token = object_proxy.mint_token(_BUCKET, _KEY)

    with TestClient(_make_app()) as client:
        response = client.head(f"/api/objects/{token}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.headers["content-length"] == str(len(_BYTES))
    # HEAD must not drain the body — only head_object should have been called.
    assert fake.head_calls == [(_BUCKET, _KEY)]
    assert fake.get_calls == []
    # And the body itself is empty on HEAD.
    assert response.content == b""


def test_head_invalid_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient()
    _install_fake_client(monkeypatch, fake)

    with TestClient(_make_app()) as client:
        response = client.head("/api/objects/not-a-real-token")

    assert response.status_code == 401
    # Token rejection must happen before any S3 work is attempted.
    assert fake.head_calls == []
    assert fake.get_calls == []


def test_head_missing_object_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(missing_keys={_KEY})
    _install_fake_client(monkeypatch, fake)
    token = object_proxy.mint_token(_BUCKET, _KEY)

    with TestClient(_make_app()) as client:
        response = client.head(f"/api/objects/{token}")

    assert response.status_code == 404
    assert fake.head_calls == [(_BUCKET, _KEY)]


def test_get_returns_body_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 32.2 regression — GET must keep streaming the full body."""

    fake = _FakeClient()
    _install_fake_client(monkeypatch, fake)
    token = object_proxy.mint_token(_BUCKET, _KEY)

    with TestClient(_make_app()) as client:
        response = client.get(f"/api/objects/{token}")

    assert response.status_code == 200
    assert response.content == _BYTES
    assert response.headers["content-type"].startswith("image/webp")
    assert fake.get_calls == [(_BUCKET, _KEY)]
    assert fake.head_calls == []


def test_get_missing_object_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(missing_keys={_KEY})
    _install_fake_client(monkeypatch, fake)
    token = object_proxy.mint_token(_BUCKET, _KEY)

    with TestClient(_make_app()) as client:
        response = client.get(f"/api/objects/{token}")

    assert response.status_code == 404


def test_head_server_error_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any non-404 exception from head_object surfaces as 502 so Meta's
    URL validator sees a deterministic gateway failure instead of 500."""

    fake = _FakeClient()
    fake.head_object = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    _install_fake_client(monkeypatch, fake)
    token = object_proxy.mint_token(_BUCKET, _KEY)

    with TestClient(_make_app()) as client:
        response = client.head(f"/api/objects/{token}")

    assert response.status_code == 502
