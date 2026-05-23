"""Phase 15 — /api/chat/upload endpoint integration tests.

Validates MIME + extension + size guards and the base64 round-trip.
"""

from __future__ import annotations

import asyncio
import importlib
from base64 import b64decode
from pathlib import Path

import pytest


def _reload_with_tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    overlay_file = tmp_path / ".password_override.json"
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-must-be-long-enough")
    monkeypatch.setenv("NEXUS_PASSWORD", "test-password-1234")

    import database

    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    for name in (
        "auth_overlay",
        "settings_service",
        "events",
        "resources_store",
    ):
        if name in importlib.sys.modules:
            importlib.reload(importlib.sys.modules[name])

    import auth_overlay

    monkeypatch.setattr(auth_overlay, "_OVERLAY_PATH", overlay_file)
    return database


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = _reload_with_tmp_db(monkeypatch, tmp_path)
    asyncio.run(database.init_db())
    return database


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    for name in (
        "routers.deps",
        "routers.auth",
        "routers.chat_uploads",
        "app",
    ):
        mod = importlib.sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)
    from fastapi.testclient import TestClient
    import app as app_module

    # Phase 27 Part 2 — the legacy /api/auth/login shim is gone (410). We
    # bypass the auth round-trip entirely: install dependency overrides so
    # current_active_user resolves to a fake superuser, then mint a legacy
    # admin JWT for the require_auth_or_token guard on /api/chat/upload.
    from tests._phase27_helpers import install_chat_test_overrides

    install_chat_test_overrides(app_module.app)

    with TestClient(app_module.app) as c:
        yield c
    app_module.app.dependency_overrides.clear()


def _login(client) -> str:  # noqa: ARG001 — kept for call-site compatibility
    from tests._phase27_helpers import mint_legacy_admin_jwt

    return mint_legacy_admin_jwt()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# Minimal valid JPEG header bytes — content sniffing is not done by the
# endpoint, but we keep realistic bytes for the round-trip assertion.
_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a4944"
    "415478da6300010000000500010d0a2db40000000049454e44ae426082"
)
_WEBP = b"RIFF\x1c\x00\x00\x00WEBPVP8L\x0f\x00\x00\x00\x2f\x00\x00\x00\x00\x4f\x00\x00\x00\x00"


@pytest.mark.integration
def test_upload_jpeg_returns_data_uri(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("photo.jpg", _JPEG, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mime"] == "image/jpeg"
    assert body["size_bytes"] == len(_JPEG)
    assert body["url"].startswith("data:image/jpeg;base64,")
    b64 = body["url"].split(",", 1)[1]
    assert b64decode(b64) == _JPEG


@pytest.mark.integration
def test_upload_png_ok(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("a.png", _PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["mime"] == "image/png"


@pytest.mark.integration
def test_upload_webp_ok(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("a.webp", _WEBP, "image/webp")},
    )
    assert r.status_code == 200, r.text


@pytest.mark.integration
def test_upload_rejects_gif(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("a.gif", b"GIF89a", "image/gif")},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_upload_rejects_wrong_extension(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("evil.exe", _JPEG, "image/jpeg")},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_upload_rejects_empty(client) -> None:
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("a.png", b"", "image/png")},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_upload_rejects_oversize(client, monkeypatch) -> None:
    from rag.config import settings as cfg

    monkeypatch.setattr(cfg, "vision_upload_max_bytes", 16, raising=False)
    t = _login(client)
    r = client.post(
        "/api/chat/upload",
        headers=_auth(t),
        files={"file": ("a.jpg", _JPEG * 10, "image/jpeg")},
    )
    assert r.status_code == 413


@pytest.mark.integration
def test_upload_rejects_unauth(client) -> None:
    r = client.post(
        "/api/chat/upload",
        files={"file": ("a.jpg", _JPEG, "image/jpeg")},
    )
    assert r.status_code == 401
