"""Wikilink graph builder — called after each file's chunks are upserted.

For each ingested file we record:
    * a ``vault_notes`` row capturing the canonical title and aliases,
    * one ``vault_links`` row per outbound wikilink.

After a batch of files is processed, :func:`resolve_link_targets` walks
the table and fills ``dst_path`` for every link whose target maps to a
known note title or alias.

The retriever in ``rag.retrieval.graph`` reads from this same DB to
expand a query into a set of neighbor notes before consulting Qdrant for
the actual chunk text.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from rag.ingest_v2.graph_db import (
    connect,
    replace_links_for,
    resolve_link_targets,
    upsert_note,
)
from rag.ingest_v2.metadata import (
    extract_aliases,
    extract_title,
    extract_wikilinks_detailed,
    split_frontmatter,
)

_log = logging.getLogger(__name__)


async def index_file_links(
    conn: aiosqlite.Connection,
    *,
    path: Path,
    body: str,
    frontmatter: dict | None = None,
) -> int:
    """Upsert the note row and replace its outbound link rows.

    Returns the number of link rows written (post-dedup).
    """

    fm = frontmatter or {}
    title = extract_title(fm, body, path)
    aliases = extract_aliases(fm)

    await upsert_note(
        conn,
        path=str(path),
        title=title,
        aliases=aliases,
    )

    links = extract_wikilinks_detailed(body)
    await replace_links_for(
        conn,
        src_path=str(path),
        links=links,
    )
    await conn.commit()
    return len(links)


async def index_file(path: Path) -> int:
    """Convenience driver — opens its own connection, indexes a single file,
    and runs the resolver. Used by the watcher / incremental ingestion."""

    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    async with connect() as conn:
        written = await index_file_links(
            conn, path=path, body=body, frontmatter=frontmatter
        )
        await resolve_link_targets(conn)
    return written
