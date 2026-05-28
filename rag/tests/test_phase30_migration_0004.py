"""Phase 30.1 — Alembic migration 0004 transfer helpers + slug rewrites."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def migration_module():
    """Import the Alembic migration as a normal Python module — by file
    path, so the test never has to spin up an Alembic context."""
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0004_phase30_sqlite_to_pg.py"
    )
    spec = importlib.util.spec_from_file_location("_phase30_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slug_rewrites_map_hunter_to_canonical_slug(migration_module) -> None:
    assert migration_module.SLUG_REWRITES == {"hunter": "cozy-downloads-store"}


def test_resolve_tenant_applies_rewrites(migration_module) -> None:
    tid = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    slug_to_uuid = {"cozy-downloads-store": tid}

    assert (
        migration_module._resolve_tenant("hunter", slug_to_uuid) == tid
    ), "legacy 'hunter' slug must rewrite to the canonical Phase 29 slug"
    assert (
        migration_module._resolve_tenant("cozy-downloads-store", slug_to_uuid)
        == tid
    )
    assert migration_module._resolve_tenant("unknown", slug_to_uuid) is None
    assert migration_module._resolve_tenant(None, slug_to_uuid) is None


def test_safe_uuid_parses_strings_and_rejects_garbage(migration_module) -> None:
    valid = "11111111-1111-1111-1111-111111111111"
    assert migration_module._safe_uuid(valid) == uuid.UUID(valid)
    assert migration_module._safe_uuid(None) is None
    assert migration_module._safe_uuid("") is None
    assert migration_module._safe_uuid("not-a-uuid") is None


def test_parse_ts_handles_iso_and_trailing_z(migration_module) -> None:
    out = migration_module._parse_ts("2026-05-23T00:00:00Z")
    assert isinstance(out, datetime)
    assert out.tzinfo is not None
    assert migration_module._parse_ts(None) is None
    assert migration_module._parse_ts("garbage") is None


def test_orphan_log_writes_jsonl(tmp_path, monkeypatch, migration_module) -> None:
    log = tmp_path / "orphans.jsonl"
    monkeypatch.setattr(migration_module, "ORPHAN_LOG", log)
    migration_module._log_orphan("conversations", "abc", "missing tenant")
    migration_module._log_orphan("messages", "xyz", "bad uuid")
    lines = log.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert payloads == [
        {"table": "conversations", "id": "abc", "reason": "missing tenant"},
        {"table": "messages", "id": "xyz", "reason": "bad uuid"},
    ]


def _seed_sqlite(path: Path) -> None:
    """Build a fixture SQLite file mirroring the Phase 9/29 schema."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_id TEXT,
            tenant_id TEXT
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources TEXT,
            created_at TEXT NOT NULL,
            user_id TEXT,
            tenant_id TEXT
        );
        """
    )
    con.commit()
    con.close()


class _StubBind:
    """Captures executed inserts so we can audit the transfer pipeline
    without standing up Postgres."""

    def __init__(self) -> None:
        self.inserts: list[tuple[str, list[dict[str, Any]]]] = []

    def execute(self, stmt, params=None):  # noqa: ANN001
        sql = str(stmt).strip()
        if params and "INSERT" in sql.upper():
            normalised = params if isinstance(params, list) else [params]
            self.inserts.append((sql, normalised))
        elif params and isinstance(params, list):
            self.inserts.append((sql, params))
        return _StubResult()


class _StubResult:
    def all(self): return []  # noqa: E704
    def __iter__(self): return iter([])  # noqa: E704


def test_transfer_conversations_skips_orphans(
    tmp_path, monkeypatch, migration_module
) -> None:
    sqlite_path = tmp_path / "nexus.db"
    _seed_sqlite(sqlite_path)
    log = tmp_path / "orphans.jsonl"
    monkeypatch.setattr(migration_module, "ORPHAN_LOG", log)

    tenant_uuid = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    user_uuid = uuid.UUID("11111111-1111-1111-1111-111111111111")

    # Seed: one good row, one orphan (unknown tenant slug), one orphan
    # (malformed user_id).
    con = sqlite3.connect(sqlite_path)
    con.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
        (
            "22222222-2222-2222-2222-222222222222",
            "good",
            "2026-05-23T00:00:00Z",
            "2026-05-23T00:00:00Z",
            str(user_uuid),
            "hunter",  # rewrite-mapped to cozy-downloads-store
        ),
    )
    con.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
        (
            "33333333-3333-3333-3333-333333333333",
            "orphan-tenant",
            "2026-05-23T00:00:00Z",
            "2026-05-23T00:00:00Z",
            str(user_uuid),
            "ghost",
        ),
    )
    con.execute(
        "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
        (
            "44444444-4444-4444-4444-444444444444",
            "orphan-user",
            "2026-05-23T00:00:00Z",
            "2026-05-23T00:00:00Z",
            "not-a-uuid",
            "hunter",
        ),
    )
    con.commit()

    bind = _StubBind()
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        accepted = migration_module._transfer_conversations(
            src,
            bind,
            slug_to_uuid={"cozy-downloads-store": tenant_uuid},
            valid_users={user_uuid},
        )
    finally:
        src.close()
        con.close()

    assert accepted == {uuid.UUID("22222222-2222-2222-2222-222222222222")}
    orphans = [json.loads(line) for line in log.read_text().splitlines()]
    reasons = {o["id"]: o["reason"] for o in orphans}
    assert "33333333-3333-3333-3333-333333333333" in reasons
    assert "tenant slug unresolved" in reasons[
        "33333333-3333-3333-3333-333333333333"
    ]
    assert "44444444-4444-4444-4444-444444444444" in reasons
    assert "user_id unresolved" in reasons[
        "44444444-4444-4444-4444-444444444444"
    ]
    # The good row was flushed through bind.execute
    assert bind.inserts, "good row should have been inserted"


def test_downgrade_is_unsupported(migration_module) -> None:
    with pytest.raises(NotImplementedError):
        migration_module.downgrade()


def test_revision_chains_to_phase29(migration_module) -> None:
    assert migration_module.revision == "0004_phase30_sqlite_to_pg"
    assert (
        migration_module.down_revision == "0003_phase29_messenger_page_tenants"
    )
