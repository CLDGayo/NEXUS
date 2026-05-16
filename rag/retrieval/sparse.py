"""Sparse (BM25) retrieval arm.

Phase 3 builds the corpus lazily from a Qdrant scroll on first query and
caches it in memory for ``BM25_CACHE_TTL_SECONDS``. This keeps the chassis
single-sourced (Qdrant remains the canonical chunk store) without
requiring the Phase 2 ingest_v2 pipeline to land first.

Phase 4 will swap this for a persisted ``rank_bm25`` snapshot rebuilt by
the ingest worker, with a Redis-backed staleness signal. The public API
(``sparse_search``) does not change.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from rank_bm25 import BM25Okapi

from rag.config import settings
from rag.retrieval.dense import get_qdrant_client
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)

BM25_CACHE_TTL_SECONDS: int = 3600
SCROLL_BATCH_SIZE: int = 256

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Deterministic tokenizer shared by corpus build and query time.

    Matches must be reproducible across processes so the BM25 score is
    stable. Keep it boring: lowercase alphanumeric runs, no stemming.
    """

    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


@dataclass
class BM25Corpus:
    """Cached BM25 index over the active Qdrant collection."""

    built_at: float
    index: BM25Okapi
    chunks: list[ScoredChunk]
    tokens: list[list[str]] = field(default_factory=list)

    def is_fresh(self, ttl: int = BM25_CACHE_TTL_SECONDS) -> bool:
        return (time.time() - self.built_at) < ttl


_corpus: BM25Corpus | None = None


def _payload_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in ("text", "content", "chunk_text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def _scroll_corpus() -> list[ScoredChunk]:
    """Pull every chunk from Qdrant in batches. Empty list on failure."""

    client = get_qdrant_client()
    chunks: list[ScoredChunk] = []
    offset = None
    try:
        while True:
            batch, next_offset = await client.scroll(
                collection_name=settings.qdrant_collection,
                limit=SCROLL_BATCH_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in batch:
                payload = dict(point.payload or {})
                chunks.append(
                    ScoredChunk(
                        id=str(point.id),
                        text=_payload_text(payload),
                        score=0.0,
                        metadata=payload,
                    )
                )
            if next_offset is None:
                break
            offset = next_offset
    except Exception as exc:
        _log.warning(
            "bm25 corpus scroll failed against %s: %s",
            settings.qdrant_collection,
            exc,
        )
    return chunks


async def build_corpus() -> BM25Corpus | None:
    """Rebuild the in-memory BM25 index from the live Qdrant collection."""

    global _corpus
    chunks = await _scroll_corpus()
    chunks = [c for c in chunks if c.text]
    if not chunks:
        _corpus = None
        return None

    tokens = [tokenize(c.text) for c in chunks]
    index = BM25Okapi(tokens)
    _corpus = BM25Corpus(
        built_at=time.time(), index=index, chunks=chunks, tokens=tokens
    )
    _log.info("bm25 corpus rebuilt: %d chunks", len(chunks))
    return _corpus


async def get_corpus() -> BM25Corpus | None:
    if _corpus is not None and _corpus.is_fresh():
        return _corpus
    return await build_corpus()


def clear_corpus() -> None:
    """Test hook — drop the cached corpus."""

    global _corpus
    _corpus = None


async def sparse_search(query: str, *, k: int = 50) -> list[ScoredChunk]:
    """Score the live corpus against the query and return the top-``k``.

    Returns an empty list if the corpus is empty or cannot be built. Never
    raises so the orchestrator can rely on the dense arm in degraded mode.
    """

    if not query.strip():
        return []

    corpus = await get_corpus()
    if corpus is None:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scores = corpus.index.get_scores(query_tokens)
    # Rank by score desc; ties broken by chunk id for determinism.
    indexed = sorted(
        enumerate(scores), key=lambda pair: (pair[1], -ord(corpus.chunks[pair[0]].id[0]) if corpus.chunks[pair[0]].id else 0), reverse=True
    )
    top = indexed[:k]
    return [
        corpus.chunks[idx].with_score(float(score))
        for idx, score in top
        if score > 0
    ]
