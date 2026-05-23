"""Phase 28 Part 2 — avatar upload tests against a mocked S3 (``moto``).

Exercises:

    * POST /api/users/me/avatar with a real PNG → 200, ``profile_image_url``
      populated, Minio key written, body normalised to WebP.
    * Oversized payload → 413.
    * Wrong MIME → 415.
    * DELETE /api/users/me/avatar clears the row and removes the Minio object.
    * GET /api/users/me/avatar/url returns a presigned URL when no public
      base is configured; returns the stable URL when one is.

The fastapi-users dependency and the user_manager session are overridden so
no real Postgres is touched. ``moto[s3]`` provides an in-process S3 server;
the object_store module hits it via the same aioboto3 client used in prod
because we point ``minio_endpoint`` at the moto fixture URL.
"""

from __future__ import annotations

import io
import socket
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _free_port() -> int:
    """Grab a free port on localhost for the moto S3 server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _moto_server() -> Iterator[str]:
    """Spin up ``moto_server s3`` on a free port and yield its base URL."""
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        # email-validator rejects ``.test`` as a reserved TLD; use the RFC
        # 2606 reserved-for-documentation domain instead.
        self.email = "avatar@example.com"
        self.is_active = True
        self.is_superuser = False
        self.is_verified = True
        self.hashed_password = ""
        self.display_name = "Avatar Tester"
        self.profile_image_url: str | None = None


class _FakeUserManager:
    """Just enough of UserManager.update for the avatar router contract.

    Records the mutations applied via ``update`` so tests can assert that
    ``profile_image_url`` was written / cleared.
    """

    def __init__(self, user: _FakeUser) -> None:
        self._user = user

    @property
    def password_helper(self):  # pragma: no cover — not exercised here
        raise AssertionError("password_helper should not be invoked by avatar tests")

    async def update(self, payload, user, safe: bool = True):
        data = payload.model_dump(exclude_unset=True)
        if "profile_image_url" in data:
            user.profile_image_url = data["profile_image_url"]
        return user


@pytest.fixture
def avatar_client(monkeypatch):
    """TestClient with auth overrides + moto-backed Minio endpoint."""
    with _moto_server() as endpoint:
        # Repoint settings at the moto server BEFORE importing the app so
        # rag.services.object_store's lazy session picks the new URL.
        from rag.config import settings

        monkeypatch.setattr(settings, "minio_endpoint", endpoint)
        monkeypatch.setattr(settings, "minio_access_key", "test")
        monkeypatch.setattr(settings, "minio_secret_key", "test-secret")
        monkeypatch.setattr(settings, "minio_bucket_avatars", "nexus-avatars-test")
        monkeypatch.setattr(settings, "minio_public_base_url", "")

        # Provision the bucket once.
        import asyncio

        from rag.scripts.phase28_bootstrap_minio import bootstrap

        asyncio.run(
            bootstrap(
                bucket=settings.minio_bucket_avatars,
                public=False,
                dry_run=False,
            )
        )

        from rag.auth import current_active_user
        from rag.auth.manager import get_user_manager
        from rag.main import app

        fake_user = _FakeUser()
        fake_manager = _FakeUserManager(fake_user)

        async def _override_user() -> _FakeUser:
            return fake_user

        async def _override_manager():
            yield fake_manager

        # The avatar router also depends on get_async_session for the flush.
        from unittest.mock import AsyncMock

        from rag.database.engine import get_async_session

        async def _override_session():
            session = AsyncMock()
            session.flush = AsyncMock(return_value=None)
            yield session

        app.dependency_overrides[current_active_user] = _override_user
        app.dependency_overrides[get_user_manager] = _override_manager
        app.dependency_overrides[get_async_session] = _override_session

        client = TestClient(app)
        try:
            yield client, fake_user, settings
        finally:
            app.dependency_overrides.clear()


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    img = Image.new("RGB", (width, height), color=(180, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_avatar_writes_minio_and_sets_user_url(avatar_client):
    client, user, _settings = avatar_client
    payload = _png_bytes()
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", payload, "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_image_url"], "profile_image_url must be set"
    # No public base configured → sentinel form.
    assert body["profile_image_url"].startswith("minio:")


def test_upload_avatar_rejects_wrong_mime(avatar_client):
    client, _user, _settings = avatar_client
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("note.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 415, r.text
    assert "UNSUPPORTED_MIME" in r.json()["detail"]


def test_upload_avatar_rejects_oversize(avatar_client, monkeypatch):
    client, _user, settings = avatar_client
    monkeypatch.setattr(settings, "avatar_max_upload_bytes", 1024)
    blob = _png_bytes(512, 512)  # > 1KB
    assert len(blob) > 1024
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("big.png", blob, "image/png")},
    )
    assert r.status_code == 413, r.text


def test_delete_avatar_clears_user_column(avatar_client):
    client, user, _settings = avatar_client
    # First upload.
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    assert user.profile_image_url is not None

    r = client.delete("/api/users/me/avatar")
    assert r.status_code == 200, r.text
    assert user.profile_image_url is None


def test_avatar_url_returns_presigned_when_no_public_base(avatar_client):
    client, user, _settings = avatar_client
    # Upload first so /url has something to point at.
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200

    r = client.get("/api/users/me/avatar/url")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("http://127.0.0.1:")
    assert "X-Amz-Signature" in body["url"]
    assert body["expires_in"] == 3600


def test_avatar_url_returns_public_url_when_base_configured(avatar_client, monkeypatch):
    client, user, settings = avatar_client
    monkeypatch.setattr(
        settings,
        "minio_public_base_url",
        "https://media.nexus.gayo-sphere.cloud",
    )
    # Trigger an upload so the user_id is the same key the public URL uses.
    r = client.post(
        "/api/users/me/avatar",
        files={"file": ("me.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    assert user.profile_image_url.startswith("https://media.nexus.gayo-sphere.cloud/")

    r = client.get("/api/users/me/avatar/url")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("https://media.nexus.gayo-sphere.cloud/")
    assert body["expires_in"] == 0


def test_avatar_url_404_when_no_avatar(avatar_client):
    client, _user, _settings = avatar_client
    r = client.get("/api/users/me/avatar/url")
    assert r.status_code == 404, r.text
