"""Phase 28 Part 1 — conversations router scopes every read to ``user_id``.

Pre-Phase-28 the router exposed every row to every authenticated caller —
a multi-tenant data leak. These tests prove that user A's GETs return only
A's rows, and any attempt to fetch B's conversation by id surfaces 404.

The tests run against a temp SQLite file with the v1 schema seeded by
``database.init_db()``; the fastapi-users dependency is overridden so we do
not need a live Postgres for the auth gate.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient


class _FakeUser:
    """Minimal stand-in for ``rag.database.models.User``."""

    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid
        self.email = f"{uid}@nexus.test"
        self.is_active = True
        self.is_superuser = False
        self.is_verified = True


def _seed(db_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Sync helper: create the schema and insert ``(id, title, user_id)`` rows."""

    async def _run() -> None:
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    user_id TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT,
                    created_at TEXT NOT NULL,
                    user_id TEXT
                )
                """
            )
            for conv_id, title, user_id in rows:
                await db.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?)",
                    (conv_id, title, "2026-05-23T00:00:00+00:00", "2026-05-23T00:00:00+00:00", user_id),
                )
            await db.commit()

    asyncio.run(_run())


@pytest.fixture
def tenancy_client(tmp_path, monkeypatch):
    """Build a TestClient with:
      * SQLite redirected to ``tmp_path/nexus.db``
      * ``current_active_user`` overridden to a swappable holder so each
        test can pretend to be user A or user B without touching Postgres.
    """
    db_file = tmp_path / "nexus.db"

    # database.DB_PATH is read at every aiosqlite.connect, so a monkeypatch
    # on the module attribute is sufficient.
    import database

    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    # The conversations router imports DB_PATH directly into its namespace
    # at module import time — patch that too.
    import routers.conversations as conv_module

    monkeypatch.setattr(conv_module, "DB_PATH", str(db_file))

    from rag.auth import current_active_user
    from rag.main import app

    holder: dict[str, _FakeUser] = {}

    async def _override() -> _FakeUser:
        return holder["user"]

    app.dependency_overrides[current_active_user] = _override

    client = TestClient(app)
    try:
        yield client, holder, db_file
    finally:
        app.dependency_overrides.clear()


def test_list_returns_only_owners_rows(tenancy_client):
    client, holder, db_file = tenancy_client
    alice = _FakeUser(uuid.UUID("11111111-1111-1111-1111-111111111111"))
    bob = _FakeUser(uuid.UUID("22222222-2222-2222-2222-222222222222"))
    _seed(
        db_file,
        rows=[
            ("alice-conv-1", "alice 1", str(alice.id)),
            ("alice-conv-2", "alice 2", str(alice.id)),
            ("bob-conv-1", "bob 1", str(bob.id)),
        ],
    )

    holder["user"] = alice
    r = client.get("/api/conversations")
    assert r.status_code == 200, r.text
    ids = sorted(row["id"] for row in r.json())
    assert ids == ["alice-conv-1", "alice-conv-2"]

    holder["user"] = bob
    r = client.get("/api/conversations")
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()]
    assert ids == ["bob-conv-1"]


def test_detail_returns_404_for_foreign_owner(tenancy_client):
    client, holder, db_file = tenancy_client
    alice = _FakeUser(uuid.UUID("11111111-1111-1111-1111-111111111111"))
    bob = _FakeUser(uuid.UUID("22222222-2222-2222-2222-222222222222"))
    _seed(
        db_file,
        rows=[
            ("alice-conv-1", "alice 1", str(alice.id)),
            ("bob-conv-1", "bob 1", str(bob.id)),
        ],
    )

    holder["user"] = alice
    r = client.get("/api/conversations/bob-conv-1")
    assert r.status_code == 404, r.text


def test_delete_404_for_foreign_owner(tenancy_client):
    client, holder, db_file = tenancy_client
    alice = _FakeUser(uuid.UUID("11111111-1111-1111-1111-111111111111"))
    bob = _FakeUser(uuid.UUID("22222222-2222-2222-2222-222222222222"))
    _seed(
        db_file,
        rows=[
            ("alice-conv-1", "alice 1", str(alice.id)),
            ("bob-conv-1", "bob 1", str(bob.id)),
        ],
    )

    holder["user"] = alice
    r = client.delete("/api/conversations/bob-conv-1")
    assert r.status_code == 404, r.text

    # The row must still exist — proves the foreign DELETE didn't touch it.
    async def _exists() -> bool:
        async with aiosqlite.connect(str(db_file)) as db:
            cur = await db.execute(
                "SELECT 1 FROM conversations WHERE id = ?", ("bob-conv-1",)
            )
            return await cur.fetchone() is not None

    assert asyncio.run(_exists()) is True


def test_create_stamps_user_id(tenancy_client):
    client, holder, db_file = tenancy_client
    _seed(db_file, rows=[])
    alice = _FakeUser(uuid.UUID("11111111-1111-1111-1111-111111111111"))
    holder["user"] = alice

    r = client.post("/api/conversations", json={"title": "hello"})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    async def _user_id() -> str | None:
        async with aiosqlite.connect(str(db_file)) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT user_id FROM conversations WHERE id = ?", (new_id,)
            )
            row = await cur.fetchone()
            return row["user_id"] if row else None

    assert asyncio.run(_user_id()) == str(alice.id)
