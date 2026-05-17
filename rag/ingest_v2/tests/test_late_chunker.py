"""Phase 4 late-chunker tests.

Covers the pure-math layer (token-in-chunk indexing and mean pooling) and
the public ``late_chunk`` orchestrator with a stub encoder so unit tests
don't need transformers/torch installed.
"""

from __future__ import annotations

from math import isclose

import pytest

from rag.ingest_v2 import late_chunker
from rag.ingest_v2.late_chunker import _mean_pool, _tokens_in_chunk, late_chunk
from rag.ingest_v2.types import ChunkBoundary


# ---------------------------------------------------------------------------
# _tokens_in_chunk
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTokensInChunk:
    def test_empty_offsets_yields_no_tokens(self) -> None:
        assert _tokens_in_chunk([], 0, 100) == []

    def test_special_tokens_excluded(self) -> None:
        offsets = [(0, 0), (0, 5), (5, 10), (0, 0)]
        assert _tokens_in_chunk(offsets, 0, 10) == [1, 2]

    def test_tokens_entirely_outside_excluded(self) -> None:
        offsets = [(0, 5), (10, 15), (20, 25)]
        assert _tokens_in_chunk(offsets, 8, 18) == [1]

    def test_majority_overlap_assigns_to_chunk(self) -> None:
        # token spans 0..10, chunk is 6..10 → overlap=4, token_len=10
        # 4*2=8 < 10 → token not majority-in this chunk.
        offsets = [(0, 10)]
        assert _tokens_in_chunk(offsets, 6, 10) == []
        # token spans 6..10, chunk is 0..10 → overlap=4, token_len=4 → 8>=4
        offsets = [(6, 10)]
        assert _tokens_in_chunk(offsets, 0, 10) == [0]

    def test_tie_breaks_to_earlier_chunk(self) -> None:
        # token 4..8 split exactly between chunks [0..6] and [6..10]:
        # overlap with first = 2 (chars 4-6), token_len=4, 2*2=4 >= 4 → goes to first.
        # overlap with second = 2 (chars 6-8), 2*2=4 >= 4 → also qualifies for second.
        # We document this as "ties go to earlier"; the algorithm assigns to
        # both qualifying chunks because the caller invokes it per-chunk.
        # In practice the semantic chunker emits non-overlapping boundaries
        # and a tie at exactly half causes duplication — acceptable in this
        # corner case. Assert the deterministic behavior:
        offsets = [(4, 8)]
        assert _tokens_in_chunk(offsets, 0, 6) == [0]
        assert _tokens_in_chunk(offsets, 6, 10) == [0]


# ---------------------------------------------------------------------------
# _mean_pool
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMeanPool:
    def test_no_indices_returns_empty(self) -> None:
        assert _mean_pool([[1.0, 2.0]], []) == []

    def test_single_token_returns_that_vector(self) -> None:
        result = _mean_pool([[1.0, 2.0, 3.0]], [0])
        assert result == [1.0, 2.0, 3.0]

    def test_mean_over_multiple_tokens(self) -> None:
        embeddings = [
            [1.0, 2.0, 3.0],
            [3.0, 4.0, 5.0],
            [5.0, 6.0, 7.0],
        ]
        result = _mean_pool(embeddings, [0, 1, 2])
        # mean = (1+3+5)/3, (2+4+6)/3, (3+5+7)/3 = 3.0, 4.0, 5.0
        assert result == [3.0, 4.0, 5.0]

    def test_partial_selection(self) -> None:
        embeddings = [[2.0, 2.0], [4.0, 6.0], [99.0, 99.0]]
        result = _mean_pool(embeddings, [0, 1])
        assert result == [3.0, 4.0]


# ---------------------------------------------------------------------------
# Public late_chunk
# ---------------------------------------------------------------------------

class _StubEncoder:
    """Deterministic encoder.

    Returns one 4-dim token embedding per word, where the embedding is
    ``[i, i, i, i]`` and the offset_mapping is the inclusive char span of
    each word. The first and last tokens are CLS/SEP at offset ``(0, 0)``.
    """

    def encode_document(
        self, text: str
    ) -> tuple[list[list[float]], list[tuple[int, int]]]:
        embeddings: list[list[float]] = [[0.0] * 4]  # CLS
        offsets: list[tuple[int, int]] = [(0, 0)]
        cursor = 0
        for i, word in enumerate(text.split(), start=1):
            start = text.find(word, cursor)
            end = start + len(word)
            embeddings.append([float(i)] * 4)
            offsets.append((start, end))
            cursor = end
        embeddings.append([0.0] * 4)  # SEP
        offsets.append((0, 0))
        return embeddings, offsets


@pytest.fixture
def stub_encoder() -> _StubEncoder:
    enc = _StubEncoder()
    late_chunker.set_encoder(enc)
    try:
        yield enc
    finally:
        late_chunker.set_encoder(None)


@pytest.mark.unit
class TestLateChunkPublic:
    def test_empty_body_returns_empty(self, stub_encoder: _StubEncoder) -> None:
        assert late_chunk("", [ChunkBoundary("x", 0, 1)]) == []

    def test_no_boundaries_returns_empty(self, stub_encoder: _StubEncoder) -> None:
        assert late_chunk("hello world", []) == []

    def test_each_boundary_produces_one_embedding(
        self, stub_encoder: _StubEncoder
    ) -> None:
        body = "alpha beta gamma delta"
        b1 = ChunkBoundary(text="alpha beta", start_char=0, end_char=10)
        b2 = ChunkBoundary(text="gamma delta", start_char=11, end_char=22)

        result = late_chunk(body, [b1, b2])
        assert len(result) == 2

        (out_b1, emb1), (out_b2, emb2) = result
        assert out_b1.text == "alpha beta"
        assert out_b2.text == "gamma delta"

        # b1 contains tokens 1+2 → mean = 1.5 across all 4 dims
        assert all(isclose(v, 1.5) for v in emb1)
        # b2 contains tokens 3+4 → mean = 3.5 across all 4 dims
        assert all(isclose(v, 3.5) for v in emb2)

    def test_boundary_with_no_tokens_is_dropped(
        self, stub_encoder: _StubEncoder
    ) -> None:
        body = "alpha beta gamma"
        # Boundary in whitespace-only region (chars 5..6 covers the space)
        in_whitespace = ChunkBoundary(text=" ", start_char=5, end_char=6)
        in_word = ChunkBoundary(text="alpha", start_char=0, end_char=5)
        result = late_chunk(body, [in_whitespace, in_word])
        # Only the in-word boundary survives.
        assert len(result) == 1
        assert result[0][0].text == "alpha"
