"""Pytest coverage for the new pages: settings, changelog, api_tokens,
integrations, resources, plus the event bus and JWT-or-token auth dep.

Run from the rag/ directory:
    uv run --with pytest pytest tests/test_new_pages.py -v
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest


def _reload_with_tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Repoint DB_PATH + overlay path to tmp, then reload captured modules."""
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

    # Now override the freshly-reloaded overlay path.
    import auth_overlay
    monkeypatch.setattr(auth_overlay, "_OVERLAY_PATH", overlay_file)
    return database


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = _reload_with_tmp_db(monkeypatch, tmp_path)
    asyncio.run(database.init_db())
    return database


# ── settings_service ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_settings_service_default_fallback(db):
    import settings_service
    val = asyncio.run(settings_service.get("TOP_K"))
    assert val == 6


@pytest.mark.unit
def test_settings_service_set_then_get_roundtrips(db):
    import settings_service
    asyncio.run(settings_service.set_value("TOP_K", 12))
    assert asyncio.run(settings_service.get("TOP_K")) == 12


@pytest.mark.unit
def test_settings_service_rejects_unknown_key(db):
    import settings_service
    with pytest.raises(KeyError):
        asyncio.run(settings_service.set_value("NOT_A_KEY", "x"))


@pytest.mark.unit
def test_settings_service_coerces_types(db):
    import settings_service
    val = asyncio.run(settings_service.set_value("SEMANTIC_BREAK_THRESHOLD", "0.7"))
    assert isinstance(val, float) and abs(val - 0.7) < 1e-6


# ── auth_overlay ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_auth_overlay_env_password_default(db):
    import auth_overlay
    assert auth_overlay.verify_password("test-password-1234") is True
    assert auth_overlay.verify_password("wrong") is False


@pytest.mark.unit
def test_auth_overlay_password_rotation(db):
    import auth_overlay
    auth_overlay.set_password("brand-new-very-long-password")
    assert auth_overlay.verify_password("brand-new-very-long-password") is True
    assert auth_overlay.verify_password("test-password-1234") is False


@pytest.mark.unit
def test_auth_overlay_password_minimum_length(db):
    import auth_overlay
    with pytest.raises(ValueError):
        auth_overlay.set_password("short")


@pytest.mark.unit
def test_auth_overlay_jwt_rotation_changes_secret(db):
    import auth_overlay
    first = auth_overlay.current_jwt_secret()
    new = auth_overlay.rotate_jwt_secret()
    assert new != first
    assert auth_overlay.current_jwt_secret() == new


# ── events bus ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_events_bus_fires_subscribers(db):
    import events
    received: list[dict] = []

    async def handler(payload):
        received.append(payload)

    bus = events.EventBus()
    bus.subscribe("ingest.complete", handler)

    async def run():
        await bus.publish("ingest.complete", {"file": "x.md", "chunks": 3})
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert received == [{"file": "x.md", "chunks": 3}]


@pytest.mark.unit
def test_events_bus_isolates_failing_handlers(db):
    import events
    received: list[dict] = []

    async def bad(_payload):
        raise RuntimeError("nope")

    async def good(payload):
        received.append(payload)

    bus = events.EventBus()
    bus.subscribe("chat.complete", bad)
    bus.subscribe("chat.complete", good)

    async def run():
        await bus.publish("chat.complete", {"ok": True})
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert received == [{"ok": True}]


# ── changelog parsing ───────────────────────────────────────────────────────

@pytest.mark.unit
def test_changelog_parses_versioned_sections(db, monkeypatch, tmp_path):
    import routers.changelog as cl
    sample = tmp_path / "CHANGELOG.md"
    sample.write_text(
        """# Changelog

## [1.2.0] - 2026-06-01

### Added
- Thing A.

### Fixed
- Thing B.

## [1.1.0] - 2026-05-01

### Added
- Older thing.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cl, "_CHANGELOG_PATH", sample)
    entries = cl._load_entries()
    assert len(entries) == 2
    assert entries[0]["version"] == "1.2.0"
    assert "added" in entries[0]["type_tags"]
    assert "fixed" in entries[0]["type_tags"]


# ── resources_store ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_resources_seed_is_idempotent(db, tmp_path):
    import resources_store
    written1 = resources_store.seed_defaults()
    assert len(written1) > 0
    written2 = resources_store.seed_defaults()
    assert written2 == []


@pytest.mark.unit
def test_resources_write_and_read_roundtrip(db, tmp_path):
    import resources_store
    resources_store.write_prompt("smoke", "Smoke", "Hello world body.")
    p = resources_store.read_prompt("smoke")
    assert p is not None
    assert p["name"] == "Smoke"
    assert "Hello world body" in p["body"]


@pytest.mark.unit
def test_resources_load_active_returns_none_when_unset(db):
    import resources_store
    body = asyncio.run(resources_store.load_active_system_prompt())
    assert body is None


@pytest.mark.unit
def test_resources_load_active_returns_body_when_set(db, tmp_path):
    import resources_store
    import settings_service
    resources_store.write_prompt("active-test", "Active Test", "ACTIVE BODY")
    asyncio.run(settings_service.set_value("system_prompt_id", "active-test"))
    body = asyncio.run(resources_store.load_active_system_prompt())
    assert body == "ACTIVE BODY"


# ── API surface via TestClient ──────────────────────────────────────────────

@pytest.fixture
def client(db, monkeypatch, tmp_path):
    for name in (
        "routers.deps",
        "routers.auth",
        "routers.settings",
        "routers.changelog",
        "routers.api_tokens",
        "integrations.dispatcher",
        "routers.integrations",
        "routers.resources",
        "app",
    ):
        mod = importlib.sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)
    from fastapi.testclient import TestClient
    import app as app_module

    # Phase 27 Part 2 — the legacy /api/auth/login shim is gone (410). The
    # routes under test all guard on `require_auth` / `require_auth_or_token`,
    # which accept any JWT signed with the overlay secret. Mint one directly
    # via the test helper to avoid the dead login round-trip.
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


@pytest.mark.integration
def test_settings_get_requires_auth(client):
    r = client.get("/api/settings")
    assert r.status_code == 401


@pytest.mark.integration
def test_settings_get_and_patch_roundtrips(client):
    t = _login(client)
    r = client.get("/api/settings", headers=_auth(t))
    assert r.status_code == 200
    payload = r.json()
    assert "values" in payload
    assert payload["values"]["TOP_K"] == 6

    r = client.patch("/api/settings", headers=_auth(t), json={"TOP_K": 9})
    assert r.status_code == 200
    assert r.json()["updated"]["TOP_K"] == 9


@pytest.mark.integration
def test_settings_patch_rejects_unknown_keys(client):
    t = _login(client)
    r = client.patch("/api/settings", headers=_auth(t), json={"NOT_REAL": 1})
    assert r.status_code == 400


@pytest.mark.integration
def test_changelog_unread_and_mark_read(client):
    t = _login(client)
    r = client.get("/api/changelog/unread", headers=_auth(t))
    assert r.status_code == 200
    body = r.json()
    assert "unread_count" in body

    r = client.post("/api/changelog/mark-read", headers=_auth(t))
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.integration
def test_api_tokens_create_list_revoke(client):
    t = _login(client)
    r = client.post(
        "/api/tokens",
        headers=_auth(t),
        json={"name": "smoke", "scopes": ["chat:read"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("nxs_")
    token_id = body["id"]

    r = client.get("/api/tokens", headers=_auth(t))
    assert r.status_code == 200
    items = r.json()
    assert any(i["id"] == token_id for i in items)
    assert all("token" not in i for i in items)

    r = client.delete(f"/api/tokens/{token_id}", headers=_auth(t))
    assert r.status_code == 204


@pytest.mark.integration
def test_api_tokens_rejects_unknown_scope(client):
    t = _login(client)
    r = client.post(
        "/api/tokens",
        headers=_auth(t),
        json={"name": "bad", "scopes": ["not-a-scope"]},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_integrations_crud_and_validation(client):
    t = _login(client)
    r = client.get("/api/integrations/events", headers=_auth(t))
    assert r.status_code == 200
    events = r.json()["events"]
    assert "ingest.complete" in events

    r = client.post(
        "/api/integrations",
        headers=_auth(t),
        json={
            "type": "webhook",
            "name": "local-test",
            "config": {"url": "http://localhost:9", "secret": "shh-1234"},
            "events": ["ingest.complete"],
        },
    )
    assert r.status_code == 201, r.text
    item = r.json()
    integ_id = item["id"]
    assert item["config"]["secret"].startswith("***")

    r = client.patch(
        f"/api/integrations/{integ_id}",
        headers=_auth(t),
        json={"enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = client.delete(f"/api/integrations/{integ_id}", headers=_auth(t))
    assert r.status_code == 204


@pytest.mark.integration
def test_integrations_rejects_unknown_type(client):
    t = _login(client)
    r = client.post(
        "/api/integrations",
        headers=_auth(t),
        json={"type": "fake", "name": "x", "config": {}, "events": []},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_resources_seed_and_activate(client):
    t = _login(client)
    r = client.post("/api/resources/prompts/seed", headers=_auth(t))
    assert r.status_code == 200
    written = r.json()["written"]
    assert len(written) > 0

    r = client.get("/api/resources/prompts", headers=_auth(t))
    assert r.status_code == 200
    items = r.json()["items"]
    slug = items[0]["slug"]

    r = client.post(f"/api/resources/prompts/{slug}/activate", headers=_auth(t))
    assert r.status_code == 200
    assert r.json()["active"] == slug

    r = client.post("/api/resources/prompts/deactivate", headers=_auth(t))
    assert r.status_code == 200
    assert r.json()["active"] == ""


@pytest.mark.integration
def test_legacy_settings_password_route_returns_410(client):
    """Phase 28 Part 2 — POST /api/settings/password retired.

    Password rotation lives at POST /api/users/me/password (fastapi-users
    identity, requires the current password). The legacy route stays
    mounted to surface a deterministic 410 for any stale client. The
    /api/auth/login shim remains permanently 410 from Phase 27 Part 2.
    """
    t = _login(client)
    r = client.post(
        "/api/settings/password",
        headers=_auth(t),
        json={"old": "test-password-1234", "new": "another-secret-12345"},
    )
    assert r.status_code == 410
    assert "users/me/password" in r.json()["detail"]

    gone = client.post("/api/auth/login", json={"password": "another-secret-12345"})
    assert gone.status_code == 410
