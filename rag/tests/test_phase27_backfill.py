"""Tests for ``rag/scripts/phase27_backfill.py``.

Avoid Postgres entirely by monkeypatching ``_fetch_superuser_id`` to return a
canned UUID. The interesting behaviour lives in the SQLite half — column
addition, row stamping, idempotency, and dry-run safety.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from pathlib import Path

import pytest

from rag.scripts import phase27_backfill as bf


# Pre-Part-2 schema: no user_id columns, no user_id indexes. Matches what a
# legacy production DB looks like before the backfill runs.
_LEGACY_CONVERSATIONS = """
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_LEGACY_MESSAGES = """
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT,
    created_at TEXT NOT NULL
)
"""
_LEGACY_API_TOKENS = """
CREATE TABLE api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    scopes_csv TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
)
"""

_FAKE_UUID = str(uuid.UUID("11111111-2222-3333-4444-555555555555"))


def _seed_legacy_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(_LEGACY_CONVERSATIONS + ";")
        db.executescript(_LEGACY_MESSAGES + ";")
        db.executescript(_LEGACY_API_TOKENS + ";")
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?)",
            ("c1", "First chat", "2026-05-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?)",
            ("c2", "Second chat", "2026-05-02T00:00:00+00:00", "2026-05-02T00:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            ("m1", "c1", "user", "hello", None, "2026-05-01T00:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            ("m2", "c1", "assistant", "hi", None, "2026-05-01T00:00:01+00:00"),
        )
        db.execute(
            "INSERT INTO api_tokens (name, token_hash, prefix, scopes_csv, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("legacy", "deadbeef", "nxs_", "chat:read", "2026-05-01T00:00:00+00:00"),
        )
        db.commit()


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy.db"
    _seed_legacy_db(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _stub_superuser(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch(email: str) -> str:  # noqa: ARG001 — match signature
        return _FAKE_UUID

    monkeypatch.setattr(bf, "_fetch_superuser_id", _fake_fetch)


def _column_names(db_path: Path, table: str) -> list[str]:
    with sqlite3.connect(db_path) as db:
        return [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def _index_names(db_path: Path, table: str) -> list[str]:
    with sqlite3.connect(db_path) as db:
        return [row[0] for row in db.execute(
            f"SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='{table}'"
        ).fetchall()]


def test_dry_run_does_not_mutate_schema_or_rows(legacy_db: Path) -> None:
    reports = asyncio.run(
        bf.run(email="x@nexus.test", db_path=str(legacy_db), dry_run=True)
    )

    # Reports still say "would add" and count what would be updated.
    by_table = {r.table: r for r in reports}
    assert by_table["conversations"].added_column is True
    assert by_table["conversations"].rows_updated == 2
    assert by_table["messages"].rows_updated == 2
    assert by_table["api_tokens"].rows_updated == 1

    # But the on-disk schema is untouched.
    assert "user_id" not in _column_names(legacy_db, "conversations")
    assert "user_id" not in _column_names(legacy_db, "messages")
    assert "user_id" not in _column_names(legacy_db, "api_tokens")


def test_full_run_adds_columns_and_stamps_rows(legacy_db: Path) -> None:
    reports = asyncio.run(
        bf.run(email="x@nexus.test", db_path=str(legacy_db), dry_run=False)
    )

    by_table = {r.table: r for r in reports}
    assert by_table["conversations"].added_column is True
    assert by_table["conversations"].rows_updated == 2
    assert by_table["messages"].added_column is True
    assert by_table["messages"].rows_updated == 2
    assert by_table["api_tokens"].added_column is True
    assert by_table["api_tokens"].rows_updated == 1

    # Schema + data committed.
    for table in bf.TARGET_TABLES:
        assert "user_id" in _column_names(legacy_db, table)
        with sqlite3.connect(legacy_db) as db:
            rows = db.execute(f"SELECT user_id FROM {table}").fetchall()
        assert rows, f"{table} should have rows"
        assert all(row[0] == _FAKE_UUID for row in rows), table

    # High-cardinality tables get the index.
    assert "idx_conversations_user_id" in _index_names(legacy_db, "conversations")
    assert "idx_messages_user_id" in _index_names(legacy_db, "messages")


def test_second_run_is_idempotent(legacy_db: Path) -> None:
    asyncio.run(bf.run(email="x@nexus.test", db_path=str(legacy_db), dry_run=False))
    reports = asyncio.run(
        bf.run(email="x@nexus.test", db_path=str(legacy_db), dry_run=False)
    )
    for report in reports:
        assert report.added_column is False, report.table
        assert report.rows_updated == 0, report.table


def test_missing_superuser_raises(
    monkeypatch: pytest.MonkeyPatch, legacy_db: Path
) -> None:
    async def _missing(_email: str) -> str:
        raise RuntimeError("No active superuser with email 'x@nexus.test'")

    monkeypatch.setattr(bf, "_fetch_superuser_id", _missing)
    with pytest.raises(RuntimeError, match="No active superuser"):
        asyncio.run(
            bf.run(email="x@nexus.test", db_path=str(legacy_db), dry_run=False)
        )
