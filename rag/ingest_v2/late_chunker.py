"""Late chunking with jina-embeddings-v2-base-en.

The full document body is tokenized once and passed through the encoder.
For each ``ChunkBoundary`` produced by the semantic chunker, we slice the
token embeddings between the boundary's char offsets (via the tokenizer's
``offset_mapping``) and mean-pool to a single chunk vector:

    E_chunk = (1/N) * Σ_{i ∈ chunk} v_i

This preserves anaphoric references — every token sees the whole document's
attention before pooling — which standard chunk-then-embed cannot.

Heavy imports (``transformers``, ``torch``, ``numpy``) are deferred until
the encoder is first invoked so unit tests can substitute a stub model.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from rag.config import settings
from rag.ingest_v2.types import ChunkBoundary

_log = logging.getLogger(__name__)


class _EncoderProtocol(Protocol):
    """Subset of the jina-v2 encoder we use. Tests substitute a stub."""

    def encode_document(self, text: str) -> tuple[list[list[float]], list[tuple[int, int]]]:
        """Return ``(token_embeddings, offset_mapping)``.

        ``token_embeddings`` is a list of length seq_len, each a list of
        ``hidden_dim`` floats. ``offset_mapping`` is the same length, each
        entry ``(start_char, end_char)`` covered by that token. Special
        tokens are reported as ``(0, 0)``.
        """
        ...


_encoder: _EncoderProtocol | None = None


def get_encoder() -> _EncoderProtocol:
    global _encoder
    if _encoder is None:
        _encoder = _JinaEncoder()
    return _encoder


def set_encoder(encoder: _EncoderProtocol | None) -> None:
    """Test hook — inject a stub or clear the cache."""

    global _encoder
    _encoder = encoder


class _JinaEncoder:
    """Real encoder backed by HuggingFace transformers + torch."""

    def __init__(self) -> None:
        from transformers import AutoModel, AutoTokenizer

        model_name = settings.ingest_embed_model
        _log.info("loading late-chunk encoder %s", model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )
        self._model = AutoModel.from_pretrained(
            model_name, trust_remote_code=True
        )
        self._model.eval()
        self._max_tokens = settings.ingest_max_tokens

    def encode_document(
        self, text: str
    ) -> tuple[list[list[float]], list[tuple[int, int]]]:
        import torch

        encoding = self._tokenizer(
            text,
            return_offsets_mapping=True,
            truncation=True,
            max_length=self._max_tokens,
            return_tensors="pt",
        )
        offsets = [tuple(pair) for pair in encoding.pop("offset_mapping")[0].tolist()]

        with torch.no_grad():
            outputs = self._model(**encoding)
        # ``last_hidden_state`` shape: (batch=1, seq_len, hidden)
        token_embeddings = outputs.last_hidden_state[0].cpu().tolist()
        return token_embeddings, offsets


# ---------------------------------------------------------------------------
# Pure-math helpers — fully covered by unit tests
# ---------------------------------------------------------------------------

def _tokens_in_chunk(
    offsets: list[tuple[int, int]],
    start_char: int,
    end_char: int,
) -> list[int]:
    """Indices of tokens whose char span lies inside ``[start_char, end_char)``.

    Tokens spanning a boundary are assigned to the chunk that contains the
    majority of their characters; ties go to the earlier chunk. Special
    tokens (offset ``(0, 0)``) are always excluded.
    """

    indices: list[int] = []
    for i, (s, e) in enumerate(offsets):
        if s == 0 and e == 0:
            continue
        if e <= start_char or s >= end_char:
            continue
        overlap_start = max(s, start_char)
        overlap_end = min(e, end_char)
        overlap = max(0, overlap_end - overlap_start)
        token_len = max(1, e - s)
        if overlap * 2 >= token_len:  # majority overlap (ties go earlier)
            indices.append(i)
    return indices


def _mean_pool(token_embeddings: list[list[float]], indices: list[int]) -> list[float]:
    """Pure-Python mean over the selected token vectors."""

    if not indices:
        return []
    hidden = len(token_embeddings[0])
    acc = [0.0] * hidden
    for idx in indices:
        vec = token_embeddings[idx]
        for j, value in enumerate(vec):
            acc[j] += value
    n = float(len(indices))
    return [value / n for value in acc]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def late_chunk(
    body: str, boundaries: list[ChunkBoundary]
) -> list[tuple[ChunkBoundary, list[float]]]:
    """Return ``[(boundary, embedding), …]`` for every chunk that received
    at least one token. Boundaries that produced no tokens (e.g. whitespace
    only after tokenization truncation) are dropped.

    The body must be the *exact* string the semantic chunker measured its
    offsets against — i.e. the post-frontmatter Markdown body.
    """

    if not body or not boundaries:
        return []

    encoder = get_encoder()
    token_embeddings, offsets = encoder.encode_document(body)
    if not token_embeddings or not offsets:
        return []

    out: list[tuple[ChunkBoundary, list[float]]] = []
    for boundary in boundaries:
        indices = _tokens_in_chunk(offsets, boundary.start_char, boundary.end_char)
        embedding = _mean_pool(token_embeddings, indices)
        if not embedding:
            continue
        out.append((boundary, embedding))
    return out
