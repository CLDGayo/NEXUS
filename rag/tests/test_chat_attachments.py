"""Phase 15 — /api/chat/stream accepts attachments and threads them into
the graph state."""

from __future__ import annotations

import asyncio
import importlib
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
        "routers.chat",
        "app",
    ):
        mod = importlib.sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)
    from fastapi.testclient import TestClient
    import app as app_module

    with TestClient(app_module.app) as c:
        yield c


def _login(client) -> str:
    r = client.post("/api/auth/login", json={"password": "test-password-1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
def test_chat_stream_accepts_attachments_field(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    async def fake_stream(question, session_id, system_prompt, attachments=None):
        captured["question"] = question
        captured["attachments"] = attachments
        yield {"type": "__final__", "answer": "ok", "sources": []}

    import routers.chat as chat_module

    monkeypatch.setattr(chat_module, "_stream_graph_events", fake_stream)

    async def no_followups(*_a, **_kw):
        return []

    monkeypatch.setattr(chat_module, "generate_followups", no_followups)

    t = _login(client)
    r = client.post(
        "/api/chat/stream",
        headers=_auth(t),
        json={
            "question": "what's this?",
            "session_id": None,
            "history": [],
            "attachments": [{"type": "image", "url": "data:image/png;base64,AAA"}],
        },
    )
    assert r.status_code == 200, r.text
    # Consume the stream so the generator actually runs end-to-end.
    list(r.iter_lines())

    assert captured["question"] == "what's this?"
    assert captured["attachments"] == [
        {"type": "image", "url": "data:image/png;base64,AAA"}
    ]


@pytest.mark.integration
def test_chat_stream_without_attachments_threads_none(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    async def fake_stream(question, session_id, system_prompt, attachments=None):
        captured["attachments"] = attachments
        yield {"type": "__final__", "answer": "ok", "sources": []}

    import routers.chat as chat_module

    monkeypatch.setattr(chat_module, "_stream_graph_events", fake_stream)

    async def no_followups(*_a, **_kw):
        return []

    monkeypatch.setattr(chat_module, "generate_followups", no_followups)

    t = _login(client)
    r = client.post(
        "/api/chat/stream",
        headers=_auth(t),
        json={"question": "plain text", "session_id": None, "history": []},
    )
    assert r.status_code == 200, r.text
    list(r.iter_lines())

    assert captured["attachments"] is None
