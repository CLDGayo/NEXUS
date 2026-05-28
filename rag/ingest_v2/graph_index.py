"""Wikilink graph builder — Postgres-backed (Phase 31).

For each ingested file we:
    1. Upsert the matching ``app.documents`` row, owning a stable
       Document UUID per ``(tenant_id, file)`` pair.
    2. Replace every outbound link row for that document in
       ``app.document_links`` with the freshly parsed wikilink set.

After a batch of files is processed,
:func:`rag.ingest_v2.graph_db.resolve_link_targets` walks the link table
inside the tenant and fills ``dst_document_id`` for every edge whose
target matches a known title or alias in that tenant.

The retriever in :mod:`rag.retrieval.graph` reads from the same tables
to expand a query into neighbour notes — strictly within the active
tenant.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rag.ingest_v2.graph_db import (
    connect,
    replace_links_for,
    resolve_link_targets,
    upsert_document,
)
from rag.ingest_v2.metadata import (
    extract_aliases,
    extract_title,
    extract_wikilinks_detailed,
    split_frontmatter,
)

_log = logging.getLogger(__name__)


def _relative_path(path: Path, vault_root: Path | None) -> str:
    """Return the path string the ingest pipeline stores in Qdrant —
    matches the form ``rag/ingest_v2/metadata.extract_file_metadata``
    emits so the Document.file column stays consistent with Qdrant
    payload.file."""

    if vault_root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(vault_root.resolve()))
    except ValueError:
        return str(path)


async def index_file_links(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    path: Path,
    body: str,
    frontmatter: dict[str, Any] | None = None,
    vault_root: Path | None = None,
    chunk_total: int = 0,
    content_hash: str | None = None,
    folder: str | None = None,
    tags: tuple[str, ...] = (),
    source_kind: str = "note",
    modified_at: Any = None,
) -> uuid.UUID:
    """Upsert the Document row and replace its outbound link rows.

    Returns the resolved Document UUID (callers can pass it back into
    follow-up calls inside the same tenant). The number of edges
    written is logged at INFO so a deploy reindex emits a per-file
    summary.
    """

    fm = frontmatter or {}
    title = extract_title(fm, body, path)
    aliases = extract_aliases(fm)
    file = _relative_path(path, vault_root)

    document_id = await upsert_document(
        session,
        tenant_id=tenant_id,
        file=file,
        title=title,
        folder=folder,
        tags=tags,
        aliases=aliases,
        source_kind=source_kind,
        content_hash=content_hash,
        chunk_total=chunk_total,
        modified_at=modified_at,
    )

    links = extract_wikilinks_detailed(body)
    await replace_links_for(
        session,
        tenant_id=tenant_id,
        src_document_id=document_id,
        links=links,
    )
    _log.info(
        "phase31 graph_index: tenant=%s file=%s edges=%d",
        tenant_id,
        file,
        len(links),
    )
    return document_id


async def index_file(
    path: Path, *, tenant_id: uuid.UUID, vault_root: Path | None = None
) -> int:
    """Convenience driver — opens its own session, indexes one file, runs
    the resolver. Used by the file watcher / incremental ingestion."""

    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    async with connect() as session:
        await index_file_links(
            session,
            tenant_id=tenant_id,
            path=path,
            body=body,
            frontmatter=frontmatter,
            vault_root=vault_root,
        )
        await resolve_link_targets(session, tenant_id=tenant_id)
    return len(extract_wikilinks_detailed(body))
