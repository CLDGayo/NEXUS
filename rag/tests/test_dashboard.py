"""Pytest coverage for the live-telemetry dashboard endpoint.

Run from the rag/ directory:
    uv run --with pytest pytest tests/test_dashboard.py -v
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _reload_with_tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_file = tmp_path / "test.db"
    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-must-be-long-enough")
    monkeypatch.setenv("NEXUS_PASSWORD", "test-password-1234")
    monkeypatch.delenv("MESSENGER_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)

    import database
    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    for name in ("messenger_overlay", "routers.dashboard"):
        if name in importlib.sys.modules:
            importlib.reload(importlib.sys.modules[name])

    import messenger_overlay
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)

    import routers.dashboard as dashboard_mod
    monkeypatch.setattr(dashboard_mod, "DB_PATH", str(db_file))
    return database, dashboard_mod


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database, dashboard_mod = _reload_with_tmp_db(monkeypatch, tmp_path)
    asyncio.run(database.init_db())
    return {"db": database, "dashboard": dashboard_mod, "tmp": tmp_path}


def _seed_conversation(db_path: str, conv_id: str, title: str) -> None:
    import aiosqlite

    async def _run() -> None:
        async with aiosqlite.connect(db_path) as db:
            ts = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (conv_id, title, ts, ts),
            )
            await db.commit()

    asyncio.run(_run())


def _seed_message(
    db_path: str,
    conv_id: str,
    role: str,
    content: str,
    created_at: datetime | None = None,
) -> None:
    import aiosqlite
    import uuid

    ts = (created_at or datetime.now(timezone.utc)).isoformat()

    async def _run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, sources,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), conv_id, role, content, None, ts),
            )
            await db.commit()

    asyncio.run(_run())


@pytest.mark.unit
def test_no_random_import_in_dashboard(env):
    dashboard_mod = env["dashboard"]
    assert "random" not in dashboard_mod.__dict__, (
        "dashboard.py must not import random — all data is real"
    )


@pytest.mark.unit
def test_count_messages_reads_real_rows(env):
    db_path = env["db"].DB_PATH
    _seed_conversation(db_path, "c1", "Test")
    _seed_message(db_path, "c1", "user", "hello")
    _seed_message(db_path, "c1", "assistant", "hi")

    msgs, convs = asyncio.run(env["dashboard"]._count_messages())
    assert msgs == 2
    assert convs == 1


@pytest.mark.unit
def test_count_messages_empty_db(env):
    msgs, convs = asyncio.run(env["dashboard"]._count_messages())
    assert msgs == 0
    assert convs == 0


@pytest.mark.unit
def test_query_volume_7d_zero_fill(env):
    out = asyncio.run(env["dashboard"]._query_volume_7d())
    assert len(out) == 7
    assert all(row["queries"] == 0 for row in out)
    assert all("date" in row for row in out)


@pytest.mark.unit
def test_query_volume_7d_counts_user_messages(env):
    db_path = env["db"].DB_PATH
    _seed_conversation(db_path, "c1", "Test")
    today = datetime.now(timezone.utc)
    _seed_message(db_path, "c1", "user", "q1", today)
    _seed_message(db_path, "c1", "user", "q2", today)
    _seed_message(db_path, "c1", "assistant", "a1", today)

    out = asyncio.run(env["dashboard"]._query_volume_7d())
    today_key = today.date().isoformat()
    today_row = next(r for r in out if r["date"] == today_key)
    assert today_row["queries"] == 2


@pytest.mark.unit
def test_recent_activity_real(env):
    db_path = env["db"].DB_PATH
    _seed_conversation(db_path, "c1", "Project Phoenix")
    base = datetime.now(timezone.utc)
    _seed_message(db_path, "c1", "user", "first", base - timedelta(minutes=2))
    _seed_message(db_path, "c1", "user", "second", base - timedelta(minutes=1))
    _seed_message(db_path, "c1", "user", "third", base)
    _seed_message(db_path, "c1", "assistant", "ignored", base)

    out = asyncio.run(env["dashboard"]._recent_activity(limit=8))
    assert len(out) == 3
    assert out[0]["file"] == "Project Phoenix"
    assert out[0]["folder"] == "Chat"
    assert out[0]["status"] == "Answered"


@pytest.mark.unit
def test_count_integrations_active_vs_total(env):
    import aiosqlite

    async def _seed() -> None:
        async with aiosqlite.connect(env["db"].DB_PATH) as db:
            ts = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO integrations (type, name, config_json, events_csv,"
                " enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("webhook", "alpha", "{}", "", 1, ts, ts),
            )
            await db.execute(
                "INSERT INTO integrations (type, name, config_json, events_csv,"
                " enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("webhook", "beta", "{}", "", 0, ts, ts),
            )
            await db.commit()

    asyncio.run(_seed())
    active, total = asyncio.run(env["dashboard"]._count_integrations())
    assert active == 1
    assert total == 2


@pytest.mark.unit
def test_messenger_active_overlay_toggles(env, monkeypatch):
    dashboard_mod = env["dashboard"]
    monkeypatch.setattr(
        dashboard_mod.messenger_overlay, "current_verify_token", lambda: None
    )
    monkeypatch.setattr(
        dashboard_mod.messenger_overlay, "current_page_access_token", lambda: None
    )
    assert dashboard_mod._messenger_active() is False

    monkeypatch.setattr(
        dashboard_mod.messenger_overlay,
        "current_verify_token",
        lambda: "verify-token-very-long",
    )
    monkeypatch.setattr(
        dashboard_mod.messenger_overlay,
        "current_page_access_token",
        lambda: "PAT-very-long-secret",
    )
    assert dashboard_mod._messenger_active() is True


@pytest.mark.unit
def test_avg_retrieval_latency_returns_none_without_data(env):
    out = asyncio.run(env["dashboard"]._avg_retrieval_latency())
    assert out is None


@pytest.mark.unit
def test_avg_retrieval_latency_pairs_user_assistant(env):
    db_path = env["db"].DB_PATH
    _seed_conversation(db_path, "c1", "Test")
    base = datetime.now(timezone.utc)
    for i in range(4):
        _seed_message(db_path, "c1", "user", "q", base + timedelta(seconds=i * 10))
        _seed_message(
            db_path,
            "c1",
            "assistant",
            "a",
            base + timedelta(seconds=i * 10 + 2),
        )

    out = asyncio.run(env["dashboard"]._avg_retrieval_latency())
    assert out is not None
    assert 1.5 <= out <= 2.5


@pytest.mark.unit
def test_ingestion_7d_zero_fill_when_vault_empty(env):
    out = env["dashboard"]._ingestion_7d()
    assert len(out) == 7
    assert all(row["chunks"] == 0 for row in out)


@pytest.mark.unit
def test_stats_payload_shape_no_mocks(env, monkeypatch):
    dashboard_mod = env["dashboard"]

    async def _no_qdrant() -> bool:
        return False

    async def _no_chunks() -> int:
        return 0

    monkeypatch.setattr(dashboard_mod, "_ping_qdrant", _no_qdrant)
    monkeypatch.setattr(dashboard_mod, "_qdrant_chunk_count", _no_chunks)

    payload = asyncio.run(dashboard_mod.stats())

    assert set(payload["kpis"].keys()) == {
        "total_notes",
        "total_chunks",
        "total_messages",
        "total_conversations",
        "active_integrations",
        "pending_inbox",
        "avg_retrieval_latency_s",
    }
    assert "groq_usage" not in payload, "Mocked groq_usage panel must be gone"
    assert set(payload["health"].keys()) == {"qdrant", "groq", "messenger", "watcher"}
    assert set(payload["activity"].keys()) == {
        "active_integrations",
        "total_integrations",
        "messenger_active",
        "uptime_seconds",
        "model",
    }
    assert payload["activity"]["uptime_seconds"] >= 0
    assert isinstance(payload["charts"]["query_volume"], list)
    assert isinstance(payload["charts"]["ingestion"], list)
