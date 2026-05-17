"""SQLite-backed wikilink graph for Phase 7 GraphRAG arm.

Two tables:

* ``vault_notes(path, title, aliases_json, updated_at)`` — one row per
  ingested note. ``title`` and ``aliases`` feed the entity-resolution
  step at query time.
* ``vault_links(src_path, dst_target, dst_path, anchor, alias)`` — one
  row per outbound wikilink. ``dst_target`` is the raw bracket text
  (``"Project Alpha"``); ``dst_path`` is the resolved file path, filled
  in by :func:`resolve_link_targets` after all notes are indexed.

The DB lives at ``rag/data/nexus_graph.db`` — separate from the existing
``nexus.db`` so the graph schema can evolve without colliding with the
conversation/auth tables.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "nexus_graph.db"


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS vault_notes (
        path TEXT PRIMARY KEY,
        title TEXT,
        aliases_json TEXT NOT NULL DEFAULT '[]',
        updated_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vault_notes_title ON vault_notes(title)",
    """
    CREATE TABLE IF NOT EXISTS vault_links (
        src_path TEXT NOT NULL,
        dst_target TEXT NOT NULL,
        dst_path TEXT,
        anchor TEXT,
        alias TEXT,
        PRIMARY KEY (src_path, dst_target, anchor)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vault_links_dst_path ON vault_links(dst_path)",
    "CREATE INDEX IF NOT EXISTS idx_vault_links_dst_target ON vault_links(dst_target)",
    "CREATE INDEX IF NOT EXISTS idx_vault_links_src_path ON vault_links(src_path)",
)


def graph_db_path() -> str:
    """Resolve the on-disk path. Honors ``NEXUS_GRAPH_DB`` for tests."""

    override = os.environ.get("NEXUS_GRAPH_DB")
    if override:
        return override
    return str(_DEFAULT_DB_PATH)


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Create tables + indexes if missing. Safe to call repeatedly."""

    for statement in _SCHEMA_STATEMENTS:
        await conn.execute(statement)
    await conn.commit()


@asynccontextmanager
async def connect(path: str | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """Open a connection with FK + WAL enabled and the schema initialized."""

    target = path or graph_db_path()
    parent = Path(target).parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(target) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA journal_mode = WAL")
        await init_schema(conn)
        yield conn


async def upsert_note(
    conn: aiosqlite.Connection,
    *,
    path: str,
    title: str | None,
    aliases: tuple[str, ...],
) -> None:
    """Insert or replace one note row. ``aliases`` stored as JSON list."""

    await conn.execute(
        """
        INSERT INTO vault_notes(path, title, aliases_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            aliases_json=excluded.aliases_json,
            updated_at=excluded.updated_at
        """,
        (path, title, json.dumps(list(aliases)), int(time.time())),
    )


async def replace_links_for(
    conn: aiosqlite.Connection,
    *,
    src_path: str,
    links: tuple[tuple[str, str | None, str | None], ...],
) -> None:
    """Replace all outbound links for ``src_path``.

    Each entry in ``links`` is ``(dst_target, anchor, alias)``. ``anchor``
    is the empty string (NOT NULL) when absent so the composite primary
    key behaves predictably.
    """

    await conn.execute("DELETE FROM vault_links WHERE src_path = ?", (src_path,))
    rows: list[tuple[str, str, str | None, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for dst_target, anchor, alias in links:
        anchor_norm = anchor or ""
        key = (dst_target, anchor_norm)
        if key in seen:
            continue
        seen.add(key)
        rows.append((src_path, dst_target, None, anchor_norm, alias))

    if rows:
        await conn.executemany(
            """
            INSERT INTO vault_links(src_path, dst_target, dst_path, anchor, alias)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


async def resolve_link_targets(conn: aiosqlite.Connection) -> int:
    """Populate ``vault_links.dst_path`` by joining ``dst_target`` against
    ``vault_notes.title`` and the JSON aliases. Returns rows updated."""

    # Reset all dst_path values so a renamed note doesn't keep its stale
    # resolution forever.
    await conn.execute("UPDATE vault_links SET dst_path = NULL")

    # Title-based resolution — exact match against vault_notes.title.
    cur = await conn.execute(
        """
        UPDATE vault_links
        SET dst_path = (
            SELECT path FROM vault_notes
            WHERE vault_notes.title = vault_links.dst_target
            LIMIT 1
        )
        WHERE dst_path IS NULL
        """
    )
    title_resolved = cur.rowcount or 0

    # Alias-based resolution — scan only unresolved rows.
    aliases_rows = await conn.execute_fetchall(
        "SELECT path, aliases_json FROM vault_notes WHERE aliases_json != '[]'"
    )
    alias_to_path: dict[str, str] = {}
    for row in aliases_rows:
        try:
            for alias in json.loads(row[1]):
                if isinstance(alias, str) and alias and alias not in alias_to_path:
                    alias_to_path[alias] = row[0]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    alias_resolved = 0
    if alias_to_path:
        unresolved = await conn.execute_fetchall(
            """
            SELECT rowid, dst_target FROM vault_links
            WHERE dst_path IS NULL
            """
        )
        updates: list[tuple[str, int]] = []
        for rowid, dst_target in unresolved:
            path = alias_to_path.get(dst_target)
            if path:
                updates.append((path, rowid))
        if updates:
            await conn.executemany(
                "UPDATE vault_links SET dst_path = ? WHERE rowid = ?",
                updates,
            )
            alias_resolved = len(updates)

    await conn.commit()
    return title_resolved + alias_resolved


async def fetch_note_titles(
    conn: aiosqlite.Connection,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return ``(path, title, aliases)`` for every indexed note."""

    rows = await conn.execute_fetchall(
        "SELECT path, title, aliases_json FROM vault_notes"
    )
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for path, title, aliases_json in rows:
        try:
            aliases = tuple(
                a for a in json.loads(aliases_json) if isinstance(a, str)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            aliases = ()
        out.append((path, title or "", aliases))
    return tuple(out)


async def neighbors_of(
    conn: aiosqlite.Connection,
    path: str,
    *,
    include_unresolved: bool = False,
) -> tuple[str, ...]:
    """Return paths linked to ``path`` (both directions), deduplicated.

    Forward edges: ``src_path = path AND dst_path IS NOT NULL``.
    Reverse edges: ``dst_path = path``.
    """

    forward_clause = "AND dst_path IS NOT NULL"
    if include_unresolved:
        forward_clause = ""

    rows = await conn.execute_fetchall(
        f"""
        SELECT dst_path FROM vault_links
        WHERE src_path = ? {forward_clause}
        UNION
        SELECT src_path FROM vault_links WHERE dst_path = ?
        """,
        (path, path),
    )
    seen: dict[str, None] = {}
    for (value,) in rows:
        if value and value != path:
            seen.setdefault(value, None)
    return tuple(seen.keys())


# ---------------------------------------------------------------------------
# Convenience accessors for tests + integration
# ---------------------------------------------------------------------------

async def all_links(
    conn: aiosqlite.Connection,
) -> tuple[dict[str, Any], ...]:
    rows = await conn.execute_fetchall(
        "SELECT src_path, dst_target, dst_path, anchor, alias FROM vault_links"
    )
    return tuple(
        {
            "src_path": r[0],
            "dst_target": r[1],
            "dst_path": r[2],
            "anchor": r[3],
            "alias": r[4],
        }
        for r in rows
    )
