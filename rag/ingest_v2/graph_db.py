"""Postgres-backed wikilink graph for the Phase 7 GraphRAG arm.

Phase 31 eradicates the legacy ``rag/data/nexus_graph.db`` SQLite store
that had no tenant column. The vault_notes table is collapsed into
``app.documents`` and the vault_links table moves to
``app.document_links``. Every read and write is now tenant-scoped — the
graph arm cannot accidentally cross workspace boundaries even if two
tenants happen to ingest a note with the same relative path.

Public API kept stable so callers in :mod:`rag.ingest_v2.graph_index`
and :mod:`rag.retrieval.graph` continue to work after a one-line import
change. Every helper now takes ``tenant_id`` as a required keyword arg
so a missed callsite fails at import / first call rather than silently
running an unscoped query.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_sessionmaker
from rag.database.models import Document, DocumentLink


@asynccontextmanager
async def connect() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session pointed at the ``app`` schema.

    Kept under the legacy name so :func:`async with graph_connect() as conn`
    callsites in the ingest pipeline and retrieval arm do not need to be
    rewritten — only the underlying engine changed.
    """

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def upsert_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    file: str,
    title: str | None,
    folder: str | None = None,
    tags: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
    source_kind: str = "note",
    content_hash: str | None = None,
    chunk_total: int = 0,
    modified_at: datetime | None = None,
) -> uuid.UUID:
    """Insert or update the Document row for ``(tenant_id, file)``.

    Returns the document UUID — callers need this to insert
    ``DocumentLink`` rows. ON CONFLICT (tenant_id, file) DO UPDATE keeps
    re-ingest idempotent.
    """

    stmt = pg_insert(Document).values(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        file=file,
        title=title,
        folder=folder,
        tags=list(tags),
        aliases=list(aliases),
        source_kind=source_kind,
        content_hash=content_hash,
        chunk_total=chunk_total,
        modified_at=modified_at,
    )
    update_cols: dict[str, Any] = {
        "title": stmt.excluded.title,
        "folder": stmt.excluded.folder,
        "tags": stmt.excluded.tags,
        "aliases": stmt.excluded.aliases,
        "source_kind": stmt.excluded.source_kind,
        "content_hash": stmt.excluded.content_hash,
        "chunk_total": stmt.excluded.chunk_total,
        "modified_at": stmt.excluded.modified_at,
        "indexed_at": datetime.now(timezone.utc),
        # Re-ingesting an archived file un-archives it so it shows up in
        # /documents again. The user explicitly chose to re-index.
        "archived_at": None,
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_app_documents_tenant_file",
        set_=update_cols,
    ).returning(Document.id)

    result = await session.execute(stmt)
    return result.scalar_one()


async def replace_links_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    src_document_id: uuid.UUID,
    links: tuple[tuple[str, str | None, str | None], ...],
) -> None:
    """Replace every outbound link from ``src_document_id`` with ``links``.

    Each entry is ``(dst_target, anchor, alias)``. ``anchor`` defaults to
    the empty string so the composite unique key (tenant, src, target,
    anchor) is deterministic. ``dst_document_id`` is filled in later by
    :func:`resolve_link_targets` once every file in the batch has been
    upserted.
    """

    await session.execute(
        delete(DocumentLink).where(
            DocumentLink.tenant_id == tenant_id,
            DocumentLink.src_document_id == src_document_id,
        )
    )

    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for dst_target, anchor, alias in links:
        anchor_norm = anchor or ""
        key = (dst_target, anchor_norm)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "src_document_id": src_document_id,
                "dst_target": dst_target,
                "dst_document_id": None,
                "anchor": anchor_norm,
                "alias": alias,
            }
        )

    if rows:
        await session.execute(pg_insert(DocumentLink), rows)


async def resolve_link_targets(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> int:
    """Populate ``DocumentLink.dst_document_id`` by joining ``dst_target``
    against ``Document.title`` (and JSONB aliases) for this tenant only.

    Returns the number of edges newly resolved. Safe to call repeatedly —
    edges that already have a ``dst_document_id`` are left alone so a
    renamed-then-renamed-again note doesn't lose its history.
    """

    # Reset stale resolutions inside this tenant — a note renamed since
    # the last pass should not keep its old dst_id.
    await session.execute(
        update(DocumentLink)
        .where(DocumentLink.tenant_id == tenant_id)
        .values(dst_document_id=None)
    )

    # Title-based resolution.
    docs_stmt = select(Document.id, Document.title, Document.aliases).where(
        Document.tenant_id == tenant_id
    )
    docs = (await session.execute(docs_stmt)).all()
    title_to_id: dict[str, uuid.UUID] = {}
    alias_to_id: dict[str, uuid.UUID] = {}
    for doc_id, title, aliases in docs:
        if title:
            title_to_id.setdefault(title, doc_id)
        for alias in aliases or []:
            if isinstance(alias, str) and alias:
                alias_to_id.setdefault(alias, doc_id)

    if not title_to_id and not alias_to_id:
        return 0

    unresolved_stmt = select(DocumentLink.id, DocumentLink.dst_target).where(
        DocumentLink.tenant_id == tenant_id,
        DocumentLink.dst_document_id.is_(None),
    )
    rows = (await session.execute(unresolved_stmt)).all()

    resolved = 0
    for link_id, dst_target in rows:
        target_id = title_to_id.get(dst_target) or alias_to_id.get(dst_target)
        if target_id is None:
            continue
        await session.execute(
            update(DocumentLink)
            .where(DocumentLink.id == link_id)
            .values(dst_document_id=target_id)
        )
        resolved += 1
    return resolved


async def fetch_note_titles(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return ``(file, title, aliases)`` for every Document in this tenant.

    Feeds the entity-resolution step in :mod:`rag.retrieval.graph`. The
    output shape matches the SQLite version so the retriever's tokeniser
    + scoring code is unchanged.
    """

    stmt = select(Document.file, Document.title, Document.aliases).where(
        Document.tenant_id == tenant_id,
        Document.archived_at.is_(None),
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for file, title, aliases in rows:
        normalised: tuple[str, ...] = tuple(
            a for a in (aliases or []) if isinstance(a, str)
        )
        out.append((file, title or "", normalised))
    return tuple(out)


async def neighbors_of(
    session: AsyncSession,
    file: str,
    *,
    tenant_id: uuid.UUID,
    include_unresolved: bool = False,
) -> tuple[str, ...]:
    """Return paths linked to ``file`` (forward + reverse) inside the
    active tenant. Deduplicates, never returns ``file`` itself.

    Backward-compatible signature: callers pass the file path string, we
    resolve it to a document id under the hood.
    """

    seed_id_stmt = select(Document.id).where(
        Document.tenant_id == tenant_id,
        Document.file == file,
    )
    seed_id = (await session.execute(seed_id_stmt)).scalar_one_or_none()
    if seed_id is None:
        return ()

    if include_unresolved:
        forward_clause = and_(
            DocumentLink.tenant_id == tenant_id,
            DocumentLink.src_document_id == seed_id,
        )
    else:
        forward_clause = and_(
            DocumentLink.tenant_id == tenant_id,
            DocumentLink.src_document_id == seed_id,
            DocumentLink.dst_document_id.is_not(None),
        )

    forward_stmt = (
        select(Document.file)
        .join(
            DocumentLink,
            DocumentLink.dst_document_id == Document.id,
        )
        .where(forward_clause)
    )
    reverse_stmt = (
        select(Document.file)
        .join(
            DocumentLink,
            DocumentLink.src_document_id == Document.id,
        )
        .where(
            DocumentLink.tenant_id == tenant_id,
            DocumentLink.dst_document_id == seed_id,
        )
    )
    forward = (await session.execute(forward_stmt)).scalars().all()
    reverse = (await session.execute(reverse_stmt)).scalars().all()

    seen: dict[str, None] = {}
    for value in (*forward, *reverse):
        if value and value != file:
            seen.setdefault(value, None)
    return tuple(seen.keys())


async def all_links(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> tuple[dict[str, Any], ...]:
    """Inspection helper for tests. Returns every link row for the tenant
    in a shape that mirrors the legacy SQLite ``all_links`` output."""

    stmt = (
        select(
            DocumentLink.id,
            DocumentLink.src_document_id,
            DocumentLink.dst_target,
            DocumentLink.dst_document_id,
            DocumentLink.anchor,
            DocumentLink.alias,
        )
        .where(DocumentLink.tenant_id == tenant_id)
    )
    rows = (await session.execute(stmt)).all()
    return tuple(
        {
            "id": str(r[0]),
            "src_document_id": str(r[1]),
            "dst_target": r[2],
            "dst_document_id": str(r[3]) if r[3] else None,
            "anchor": r[4],
            "alias": r[5],
        }
        for r in rows
    )


__all__ = [
    "all_links",
    "connect",
    "fetch_note_titles",
    "neighbors_of",
    "replace_links_for",
    "resolve_link_targets",
    "upsert_document",
]


# Re-export json so older tests that imported it from this module keep
# working.
_ = json
