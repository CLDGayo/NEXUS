"""Database package.

The legacy aiosqlite tables (``conversations``, ``messages``, ``settings``,
``integrations``, ``api_tokens``) live here directly so existing flat imports
(``from database import DB_PATH, init_db, ...``) and ``monkeypatch.setattr(
database, "DB_PATH", ...)`` calls in tests keep working without modification.

The SQLAlchemy ``Base`` (``rag.database.base``), the async engine
(``rag.database.engine``), and the ORM models (``rag.database.models``) are
sibling sub-modules pulled in lazily by the auth + chat surfaces.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import aiosqlite

# Phase 9 path: ``rag/data/nexus.db`` (one level above this package
# directory, so the file lives next to ``rag/main.py`` exactly as before
# the Phase 27 package promotion).
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "nexus.db")

_CREATE_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT,
    created_at TEXT NOT NULL
)
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_INTEGRATIONS = """
CREATE TABLE IF NOT EXISTS integrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    events_csv TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_fired_at TEXT,
    last_status TEXT
)
"""

_CREATE_API_TOKENS = """
CREATE TABLE IF NOT EXISTS api_tokens (
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

_INDEX_TOKEN_HASH = (
    "CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash)"
)


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_CONVERSATIONS)
        await db.execute(_CREATE_MESSAGES)
        await db.execute(_CREATE_SETTINGS)
        await db.execute(_CREATE_INTEGRATIONS)
        await db.execute(_CREATE_API_TOKENS)
        await db.execute(_INDEX_TOKEN_HASH)
        await db.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


__all__ = ["DB_PATH", "init_db", "new_id", "now_iso"]
