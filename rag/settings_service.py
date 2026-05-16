"""Typed settings service over the `settings` SQLite table.

Settings are stored as JSON-serialized scalars keyed by name. Values fall back
to environment variables (or hard-coded defaults) when not set in the DB.

The allow-list `SETTING_KEYS` is the only set of keys the API will accept on
PATCH; anything else returns 400.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

import aiosqlite

from database import DB_PATH, now_iso

SettingType = Literal["int", "float", "str", "bool"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: SettingType
    default: Any
    env: str | None = None
    secret: bool = False
    description: str = ""


SETTING_KEYS: dict[str, SettingSpec] = {
    s.key: s
    for s in (
        SettingSpec("TOP_K", "int", 6, "TOP_K", description="Final chunks passed to LLM"),
        SettingSpec("RETRIEVE_K", "int", 50, "RETRIEVE_K", description="Candidates per retrieval arm"),
        SettingSpec("CHUNK_TOKENS", "int", 400, "CHUNK_TOKENS", description="Target chunk size in tokens"),
        SettingSpec("CHUNK_OVERLAP", "int", 50, "CHUNK_OVERLAP", description="Overlap tokens between chunks"),
        SettingSpec(
            "SEMANTIC_BREAK_THRESHOLD",
            "float",
            0.55,
            "SEMANTIC_BREAK_THRESHOLD",
            description="Cosine similarity floor for semantic chunking",
        ),
        SettingSpec(
            "RERANK_CONFIDENCE_FLOOR",
            "float",
            0.30,
            "RERANK_CONFIDENCE_FLOOR",
            description="Below this score, trigger query rewrite or abstain",
        ),
        SettingSpec(
            "GROQ_MODEL",
            "str",
            "llama-3.3-70b-versatile",
            "GROQ_MODEL",
            description="Primary generation model",
        ),
        SettingSpec(
            "FOLLOWUP_MODEL",
            "str",
            "llama-3.1-8b-instant",
            "FOLLOWUP_MODEL",
            description="Follow-up question generation model",
        ),
        SettingSpec("THEME", "str", "light", None, description="UI theme (light|dark)"),
        SettingSpec(
            "system_prompt_id",
            "str",
            "",
            None,
            description="Slug of Resource prompt active in chat (empty = baked-in)",
        ),
        SettingSpec(
            "changelog_last_read",
            "str",
            "",
            None,
            description="ISO-8601 timestamp of last 'mark read' click",
        ),
    )
}


def _coerce(spec: SettingSpec, raw: Any) -> Any:
    if spec.type == "int":
        return int(raw)
    if spec.type == "float":
        return float(raw)
    if spec.type == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return str(raw)


def _from_env(spec: SettingSpec) -> Any | None:
    if not spec.env:
        return None
    raw = os.environ.get(spec.env)
    if raw is None or raw == "":
        return None
    try:
        return _coerce(spec, raw)
    except (TypeError, ValueError):
        return None


async def get(key: str) -> Any:
    """Resolve a setting: DB value → env fallback → default."""
    spec = SETTING_KEYS.get(key)
    if spec is None:
        raise KeyError(f"Unknown setting: {key}")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row is not None:
            try:
                return _coerce(spec, json.loads(row[0]))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

    env_val = _from_env(spec)
    if env_val is not None:
        return env_val
    return spec.default


async def set_value(key: str, value: Any) -> Any:
    """Validate + persist a setting; returns the coerced value."""
    spec = SETTING_KEYS.get(key)
    if spec is None:
        raise KeyError(f"Unknown setting: {key}")
    coerced = _coerce(spec, value)
    serialized = json.dumps(coerced)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, serialized, now_iso()),
        )
        await db.commit()
    return coerced


async def get_all() -> dict[str, Any]:
    """Return resolved values for every allow-listed key."""
    return {k: await get(k) for k in SETTING_KEYS}


def describe() -> list[dict[str, Any]]:
    """Static metadata for the UI."""
    return [
        {
            "key": s.key,
            "type": s.type,
            "default": s.default,
            "env": s.env,
            "description": s.description,
        }
        for s in SETTING_KEYS.values()
    ]
