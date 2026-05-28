"""End-to-end ingest pipeline.

For each source file:
    1. Multimodal parse → clean Markdown.
    2. Split frontmatter + extract file metadata.
    3. Semantic chunking on the body → ``ChunkBoundary`` list.
    4. Late chunking via jina-v2 + mean pooling → embeddings.
    5. Build ``IngestChunk`` with deterministic ids + payload.
    6. Upsert to Qdrant in batches (every payload carries ``tenant_id``).
    7. Upsert the matching ``app.documents`` row and replace its
       ``app.document_links`` edges.

Phase 31 — ``tenant_id`` (UUID) is a required keyword argument on every
public entrypoint. The Qdrant payload still uses the human-readable slug
(stamped via ``base_meta["tenant_id"] = tenant_slug``), but the
Postgres-side writes use the UUID so the FK to ``app.tenants.id`` holds.
Callers (CLI, watcher, REST shim) must therefore resolve the slug to a
UUID before invoking the pipeline.

The pipeline never raises out of ``ingest_file`` — failures become
``IngestResult(error=...)`` so the CLI driver can summarize a partial run.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rag.ingest_v2.graph_db import connect as graph_connect
from rag.ingest_v2.graph_db import resolve_link_targets
from rag.ingest_v2.graph_index import index_file_links
from rag.ingest_v2.late_chunker import late_chunk
from rag.ingest_v2.metadata import (
    extract_file_metadata,
    split_frontmatter,
    stable_chunk_id,
)
from rag.ingest_v2.multimodal import (
    UnsupportedFormatError,
    parse_to_markdown_with_vision,
)
from rag.ingest_v2.qdrant_writer import init_collection, upsert_chunks
from rag.ingest_v2.semantic_chunker import chunk_text
from rag.ingest_v2.types import IngestChunk, IngestResult

_log = logging.getLogger(__name__)

_VAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "_publish",
        ".obsidian",
        ".git",
        "rag",
        "node_modules",
        "04 - Archive",
        ".venv",
        "__pycache__",
        "screenshots",
        ".playwright-mcp",
    }
)


def iter_vault(
    root: Path, *, extensions: Iterable[str] = (".md", ".pdf")
) -> list[Path]:
    """Walk ``root`` and return ingestible files, honoring the skip set."""

    extensions = tuple(ext.lower() for ext in extensions)
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        if any(part in _VAULT_SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


async def ingest_file(
    path: Path,
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    vault_root: Path | None = None,
    collection: str | None = None,
    dry_run: bool = False,
) -> IngestResult:
    """Ingest a single source file end-to-end. Never raises.

    Both ``tenant_id`` (uuid for Postgres FK) and ``tenant_slug`` (string
    used in the Qdrant payload) are required. Callers that only have one
    must resolve the other before invoking the pipeline.
    """

    if not path.exists():
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            error=f"path does not exist: {path}",
        )

    # 1. Multimodal parse
    try:
        markdown = await parse_to_markdown_with_vision(path)
    except UnsupportedFormatError as exc:
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            skipped=True, skip_reason=str(exc),
        )
    except Exception as exc:
        _log.exception("multimodal parse failed for %s", path)
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            error=f"parse failed: {exc}",
        )

    if not markdown.strip():
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            skipped=True, skip_reason="empty document",
        )

    # 2. Frontmatter + file metadata
    front_meta, body = split_frontmatter(markdown)
    file_meta = extract_file_metadata(path, markdown, vault_root=vault_root)

    # 3. Semantic boundaries
    try:
        boundaries = chunk_text(body)
    except Exception as exc:
        _log.exception("semantic chunking failed for %s", path)
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            error=f"chunk failed: {exc}",
        )

    if not boundaries:
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            skipped=True, skip_reason="no chunks produced",
        )

    # 4. Late chunking
    try:
        chunked = late_chunk(body, boundaries)
    except Exception as exc:
        _log.exception("late chunking failed for %s", path)
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            error=f"late_chunk failed: {exc}",
        )

    if not chunked:
        return IngestResult(
            source=path, chunks_emitted=0, chunks_upserted=0,
            skipped=True, skip_reason="late chunker produced no embeddings",
        )

    # 5. Build IngestChunk objects (tenant_id slug stamped on every payload)
    chunk_total = len(chunked)
    base_meta = _file_meta_to_payload(file_meta)
    base_meta["tenant_id"] = tenant_slug
    ingest_chunks: list[IngestChunk] = []
    for index, (boundary, embedding) in enumerate(chunked):
        ingest_chunks.append(
            IngestChunk(
                id=stable_chunk_id(file_meta.file, index, boundary.text),
                text=boundary.text,
                embedding=tuple(embedding),
                metadata={
                    **base_meta,
                    "chunk_index": index,
                    "chunk_total": chunk_total,
                    "start_char": boundary.start_char,
                    "end_char": boundary.end_char,
                    "heading_path": list(boundary.heading_path),
                },
            )
        )

    if dry_run:
        return IngestResult(
            source=path, chunks_emitted=len(ingest_chunks), chunks_upserted=0,
        )

    # 6. Upsert chunks to Qdrant
    try:
        written = await upsert_chunks(ingest_chunks, collection=collection)
    except Exception as exc:
        _log.exception("qdrant upsert failed for %s", path)
        return IngestResult(
            source=path, chunks_emitted=len(ingest_chunks), chunks_upserted=0,
            error=f"upsert failed: {exc}",
        )

    # 7. Postgres registry + wikilink graph. Failure here must NOT lose
    # the chunks we just upserted, so any exception is logged and
    # swallowed — the next reindex will retry the graph writes.
    folder = _folder_from_file(file_meta.file)
    tags_value = _tags_from_frontmatter(front_meta)
    try:
        async with graph_connect() as session:
            await index_file_links(
                session,
                tenant_id=tenant_id,
                path=path,
                body=body,
                frontmatter=front_meta,
                vault_root=vault_root,
                chunk_total=chunk_total,
                content_hash=getattr(file_meta, "content_hash", None),
                folder=folder,
                tags=tags_value,
                source_kind="note",
                modified_at=getattr(file_meta, "modified_at", None),
            )
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("graph link index failed for %s: %s", path, exc)

    return IngestResult(
        source=path, chunks_emitted=len(ingest_chunks), chunks_upserted=written,
    )


async def ingest_paths(
    paths: list[Path],
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    vault_root: Path | None = None,
    collection: str | None = None,
    dry_run: bool = False,
    ensure_collection: bool = True,
) -> list[IngestResult]:
    """Ingest a sequence of files. Initializes the target collection once
    upfront unless ``ensure_collection`` is False."""

    if ensure_collection and not dry_run:
        await init_collection(collection=collection)

    results: list[IngestResult] = []
    for path in paths:
        results.append(
            await ingest_file(
                path,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                vault_root=vault_root,
                collection=collection,
                dry_run=dry_run,
            )
        )

    # After every file in the batch has registered its title + outbound
    # links, resolve target text → document ids in a single pass scoped
    # to this tenant.
    if not dry_run:
        try:
            async with graph_connect() as session:
                await resolve_link_targets(session, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("graph link resolution failed: %s", exc)

    return results


def _file_meta_to_payload(meta: Any) -> dict[str, Any]:
    """Convert FileMetadata to a JSON-storable dict (drop frontmatter dict
    so we don't bloat the Qdrant payload)."""

    raw = asdict(meta)
    raw.pop("frontmatter", None)
    return raw


def _folder_from_file(file: str) -> str | None:
    """Top-level folder name (matches the legacy ``documents.py`` shape)."""

    if not file:
        return None
    parts = Path(file).parts
    if len(parts) <= 1:
        return None
    return parts[0]


def _tags_from_frontmatter(meta: dict[str, Any] | None) -> tuple[str, ...]:
    if not meta:
        return ()
    raw = meta.get("tags")
    if raw is None:
        return ()
    if isinstance(raw, str):
        return tuple(t.strip() for t in raw.split(",") if t.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(t).strip() for t in raw if str(t).strip())
    return ()
