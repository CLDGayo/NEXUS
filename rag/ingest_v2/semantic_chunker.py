"""Semantic boundary detection via chonkie ``SemanticChunker``.

Produces ``ChunkBoundary`` instances with char offsets so the late-chunker
can map them back to token slices via the tokenizer's ``offset_mapping``.

chonkie's API has shifted between minor versions; we adapt defensively at
call time rather than pinning to a single shape.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rag.config import settings
from rag.ingest_v2.types import ChunkBoundary

_log = logging.getLogger(__name__)

_chunker: Any | None = None


def _load_chunker():
    """Construct a chonkie semantic chunker. Lazy so tests can mock."""

    from chonkie import SemanticChunker

    return SemanticChunker(
        embedding_model=settings.semantic_chunker_model,
        threshold=settings.semantic_break_threshold,
        chunk_size=settings.ingest_chunk_size,
        min_sentences=1,
    )


def get_chunker():
    global _chunker
    if _chunker is None:
        _chunker = _load_chunker()
    return _chunker


def set_chunker(chunker: Any | None) -> None:
    """Test hook."""

    global _chunker
    _chunker = chunker


def _coerce_to_boundary(
    chunk: Any, full_text: str, fallback_cursor: int
) -> ChunkBoundary | None:
    """Adapt a chonkie chunk object to our ``ChunkBoundary`` regardless of
    library version.

    Recent chonkie exposes ``.text``, ``.start_index``, ``.end_index``.
    Older versions used ``.content`` / ``.start``/``.end``. If offsets are
    missing entirely, we re-derive them with ``str.find`` from the caller's
    cursor — preserves order but does not handle duplicate substrings.
    """

    text = (
        getattr(chunk, "text", None)
        or getattr(chunk, "content", None)
        or str(chunk)
    )
    if not text:
        return None

    start = getattr(chunk, "start_index", None)
    if start is None:
        start = getattr(chunk, "start", None)
    end = getattr(chunk, "end_index", None)
    if end is None:
        end = getattr(chunk, "end", None)

    if start is None or end is None:
        # Recovery path — find the substring after the previous cursor.
        located = full_text.find(text, fallback_cursor)
        if located < 0:
            return None
        start, end = located, located + len(text)

    return ChunkBoundary(text=text, start_char=int(start), end_char=int(end))


def chunk_text(body: str) -> list[ChunkBoundary]:
    """Run semantic chunking over a single document body.

    Returns boundaries in document order. Empty input → empty list.
    Failures fall back to a coarse paragraph split so the pipeline never
    drops a document silently.
    """

    if not body or not body.strip():
        return []

    try:
        chunker = get_chunker()
        raw = chunker(body) if callable(chunker) else chunker.chunk(body)
    except Exception as exc:
        _log.warning(
            "chonkie chunk failed; falling back to paragraph split: %s", exc
        )
        return _paragraph_fallback(body)

    boundaries: list[ChunkBoundary] = []
    cursor = 0
    for raw_chunk in raw:
        boundary = _coerce_to_boundary(raw_chunk, body, cursor)
        if boundary is None:
            continue
        boundaries.append(boundary)
        cursor = boundary.end_char
    return boundaries or _paragraph_fallback(body)


def _paragraph_fallback(body: str) -> list[ChunkBoundary]:
    """Coarse split when chonkie is unavailable or errored. Splits on blank
    lines, preserves char offsets."""

    boundaries: list[ChunkBoundary] = []
    cursor = 0
    for paragraph in re.split(r"\n\s*\n", body):
        stripped = paragraph.strip()
        if not stripped:
            cursor += len(paragraph) + 2
            continue
        start = body.find(stripped, cursor)
        if start < 0:
            continue
        end = start + len(stripped)
        boundaries.append(ChunkBoundary(text=stripped, start_char=start, end_char=end))
        cursor = end
    return boundaries
