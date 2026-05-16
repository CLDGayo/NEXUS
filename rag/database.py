"""SQLite persistence for conversation history, settings, integrations, tokens."""

import os
import uuid
from datetime import datetime, timezone

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "nexus.db")

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
