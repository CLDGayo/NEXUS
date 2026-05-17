"""Ingest-side data types.

``IngestChunk`` is distinct from ``rag.retrieval.types.ScoredChunk``: the
ingest pipeline carries the raw embedding vector through to the Qdrant
writer, while the retrieval side only ever sees scores. Keeping them apart
prevents accidental coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChunkBoundary:
    """Output of the semantic boundary detector.

    Char offsets are relative to the (post-frontmatter) document body. They
    feed the late-chunker's token-range lookup via tokenizer offset_mapping.
    """

    text: str
    start_char: int
    end_char: int
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestChunk:
    """A single chunk ready for Qdrant upsert.

    ``id`` is a deterministic UUIDv5 derived from (file path, chunk index,
    content hash) so re-ingest is idempotent — same content → same point id.
    """

    id: str
    text: str
    embedding: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    """Summary returned by the pipeline per source file."""

    source: Path
    chunks_emitted: int
    chunks_upserted: int
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.skipped
