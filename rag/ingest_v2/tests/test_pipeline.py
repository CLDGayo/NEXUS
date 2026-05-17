"""Phase 4 end-to-end pipeline tests.

Stubs every heavy dep (Docling, chonkie, jina-v2, Qdrant) so the test runs
without ML libs installed. Verifies orchestration: each stage feeds the next,
``IngestChunk`` payloads contain expected metadata, dry-run skips writes,
unsupported formats skip cleanly, and errors surface as ``IngestResult.error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from rag.ingest_v2 import (
    late_chunker,
    multimodal,
    pipeline,
    qdrant_writer,
    semantic_chunker,
)
from rag.ingest_v2.types import ChunkBoundary, IngestChunk


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubChunker:
    """Splits on sentences; preserves char offsets via str.find."""

    def __call__(self, body: str) -> list[Any]:
        out: list[Any] = []
        cursor = 0
        for sentence in body.replace("\n", " ").split(". "):
            text = sentence.strip()
            if not text:
                continue
            start = body.find(text, cursor)
            if start < 0:
                continue
            end = start + len(text)
            out.append(_SimpleChunk(text=text, start_index=start, end_index=end))
            cursor = end
        return out


class _SimpleChunk:
    def __init__(self, text: str, start_index: int, end_index: int) -> None:
        self.text = text
        self.start_index = start_index
        self.end_index = end_index


class _StubEncoder:
    """One 4-dim token per word — same pattern as the late_chunker tests."""

    def encode_document(self, text: str) -> tuple[list[list[float]], list[tuple[int, int]]]:
        embeddings: list[list[float]] = [[0.0] * 4]
        offsets: list[tuple[int, int]] = [(0, 0)]
        cursor = 0
        for i, word in enumerate(text.split(), start=1):
            start = text.find(word, cursor)
            end = start + len(word)
            embeddings.append([float(i)] * 4)
            offsets.append((start, end))
            cursor = end
        embeddings.append([0.0] * 4)
        offsets.append((0, 0))
        return embeddings, offsets


class _StubQdrant:
    def __init__(self) -> None:
        self.collection_exists = AsyncMock(return_value=True)
        self.create_collection = AsyncMock()
        self.delete_collection = AsyncMock()
        self.upsert = AsyncMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stubbed_pipeline() -> None:
    semantic_chunker.set_chunker(_StubChunker())
    late_chunker.set_encoder(_StubEncoder())
    qdrant_writer.set_client(_StubQdrant())  # type: ignore[arg-type]
    multimodal.set_converter(None)
    yield
    semantic_chunker.set_chunker(None)
    late_chunker.set_encoder(None)
    qdrant_writer.set_client(None)
    multimodal.set_converter(None)


@pytest.fixture
def sample_note(tmp_path: Path) -> Path:
    path = tmp_path / "vault" / "01 - Projects" / "alpha.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "title: Project Alpha\n"
        "tags: [active]\n"
        "---\n"
        "# Project Alpha\n\n"
        "Sentence one. Sentence two. Sentence three."
    )
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_ingest_file_end_to_end(sample_note: Path) -> None:
    # sample_note path: <tmp>/vault/01 - Projects/alpha.md
    # parents[1] = <tmp>/vault  (the vault root)
    result = await pipeline.ingest_file(
        sample_note,
        vault_root=sample_note.parents[1],
        collection="test-collection",
    )
    assert result.succeeded
    assert result.error is None
    assert result.chunks_emitted >= 1
    assert result.chunks_upserted == result.chunks_emitted


@pytest.mark.unit
async def test_ingest_file_dry_run_skips_upsert(sample_note: Path) -> None:
    qdrant = _StubQdrant()
    qdrant_writer.set_client(qdrant)  # type: ignore[arg-type]
    result = await pipeline.ingest_file(
        sample_note, collection="test-collection", dry_run=True
    )
    assert result.succeeded
    assert result.chunks_emitted >= 1
    assert result.chunks_upserted == 0
    qdrant.upsert.assert_not_awaited()


@pytest.mark.unit
async def test_ingest_file_emits_metadata_on_chunks(sample_note: Path) -> None:
    captured: list[IngestChunk] = []

    async def _capture(chunks, *, collection=None, batch_size=64):  # type: ignore[no-untyped-def]
        captured.extend(chunks)
        return len(chunks)

    import rag.ingest_v2.pipeline as pipeline_module

    pipeline_module.upsert_chunks = _capture  # type: ignore[assignment]
    try:
        result = await pipeline.ingest_file(
            sample_note,
            vault_root=sample_note.parents[1],
            collection="test-collection",
        )
    finally:
        # Restore module-level import
        from rag.ingest_v2.qdrant_writer import upsert_chunks
        pipeline_module.upsert_chunks = upsert_chunks  # type: ignore[assignment]

    assert result.succeeded
    assert captured, "no chunks captured by stubbed upsert"
    sample = captured[0]
    assert sample.metadata["file"] == str(sample_note)
    assert sample.metadata["folder"] == "01 - Projects"
    assert sample.metadata["title"] == "Project Alpha"
    assert sample.metadata["chunk_index"] == 0
    assert sample.metadata["chunk_total"] == len(captured)
    assert sample.embedding  # non-empty embedding vector
    # 768-dim default applies to the real model only; the stub emits 4-dim.
    assert len(sample.embedding) == 4


# ---------------------------------------------------------------------------
# Skip + error paths
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_unsupported_format_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "weird.xyz"
    path.write_text("anything")
    result = await pipeline.ingest_file(path)
    assert result.skipped
    assert "no parser registered" in (result.skip_reason or "")


@pytest.mark.unit
async def test_missing_path_returns_error(tmp_path: Path) -> None:
    result = await pipeline.ingest_file(tmp_path / "does-not-exist.md")
    assert result.error is not None
    assert "does not exist" in result.error


@pytest.mark.unit
async def test_empty_body_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("")
    result = await pipeline.ingest_file(path)
    assert result.skipped


# ---------------------------------------------------------------------------
# Vault walk
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_iter_vault_skips_known_dirs(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "01 - Projects").mkdir(parents=True)
    (vault / "01 - Projects" / "alpha.md").write_text("# alpha")
    (vault / "_publish").mkdir()
    (vault / "_publish" / "site.md").write_text("# excluded")
    (vault / "04 - Archive").mkdir()
    (vault / "04 - Archive" / "old.md").write_text("# excluded")

    paths = pipeline.iter_vault(vault, extensions=(".md",))
    names = {p.name for p in paths}
    assert "alpha.md" in names
    assert "site.md" not in names
    assert "old.md" not in names
