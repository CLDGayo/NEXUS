"""Phase 4 semantic chunker tests.

Real chonkie is optional. When absent, the fallback paragraph splitter must
still produce non-empty, char-anchored boundaries. When present (or stubbed),
the coercion layer adapts to the chunk object's available attributes.
"""

from __future__ import annotations

import pytest

from rag.ingest_v2 import semantic_chunker
from rag.ingest_v2.types import ChunkBoundary


@pytest.fixture(autouse=True)
def reset_chunker() -> None:
    semantic_chunker.set_chunker(None)
    yield
    semantic_chunker.set_chunker(None)


@pytest.mark.unit
class TestFallback:
    """If no chunker is configured AND chonkie can't load, we must still
    emit paragraph-anchored boundaries rather than dropping the document."""

    def test_paragraph_split_via_fallback(self) -> None:
        # Force fallback by installing a chunker that raises.
        class _Boom:
            def __call__(self, *args, **kwargs):
                raise RuntimeError("simulated failure")

        semantic_chunker.set_chunker(_Boom())

        body = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        boundaries = semantic_chunker.chunk_text(body)
        texts = [b.text for b in boundaries]
        assert texts == ["Paragraph one.", "Paragraph two.", "Paragraph three."]
        # Offsets must point at the real substring positions
        for b in boundaries:
            assert body[b.start_char:b.end_char] == b.text

    def test_empty_body_returns_empty(self) -> None:
        assert semantic_chunker.chunk_text("") == []
        assert semantic_chunker.chunk_text("   \n  ") == []


@pytest.mark.unit
class TestStubChunker:
    """Demonstrate the coercion layer with a hand-crafted stub chunk."""

    def test_chunk_with_start_index_end_index(self) -> None:
        class _StubChunker:
            def __call__(self, body: str):
                class _Chunk:
                    text = "hello"
                    start_index = 0
                    end_index = 5
                return [_Chunk()]

        semantic_chunker.set_chunker(_StubChunker())
        boundaries = semantic_chunker.chunk_text("hello world")
        assert boundaries == [ChunkBoundary(text="hello", start_char=0, end_char=5)]

    def test_chunk_with_legacy_attrs(self) -> None:
        class _StubChunker:
            def __call__(self, body: str):
                class _Chunk:
                    content = "world"
                    start = 6
                    end = 11
                return [_Chunk()]

        semantic_chunker.set_chunker(_StubChunker())
        boundaries = semantic_chunker.chunk_text("hello world")
        assert boundaries == [ChunkBoundary(text="world", start_char=6, end_char=11)]

    def test_missing_offsets_recovered_by_substring_search(self) -> None:
        class _StubChunker:
            def __call__(self, body: str):
                class _Chunk:
                    text = "alpha"
                return [_Chunk()]

        semantic_chunker.set_chunker(_StubChunker())
        boundaries = semantic_chunker.chunk_text("alpha beta gamma")
        assert boundaries == [ChunkBoundary(text="alpha", start_char=0, end_char=5)]
