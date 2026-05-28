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

from qdrant_client.models import FieldCondition, Filter, MatchValue
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


# Phase 29 — per-tenant corpus cache. Key is the tenant slug; ``None`` is
# reserved for the legacy "everything" corpus (unfiltered) which retrieval
# code no longer uses but tests can opt into via ``build_corpus(None)``.
_corpora: dict[str | None, BM25Corpus] = {}


def _payload_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in ("text", "content", "chunk_text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _tenant_scroll_filter(tenant_slug: str | None) -> Filter | None:
    if tenant_slug is None:
        return None
    return Filter(
        must=[
            FieldCondition(
                key="tenant_id", match=MatchValue(value=tenant_slug)
            )
        ]
    )


async def _scroll_corpus(
    tenant_slug: str | None,
) -> list[ScoredChunk]:
    """Pull every chunk owned by ``tenant_slug`` from Qdrant in batches.

    ``tenant_slug=None`` scrolls the entire collection — kept as an escape
    hatch for diagnostics and the legacy path. Production retrieval always
    passes a slug. Empty list on failure.
    """

    client = get_qdrant_client()
    chunks: list[ScoredChunk] = []
    offset = None
    scroll_filter = _tenant_scroll_filter(tenant_slug)
    try:
        while True:
            batch, next_offset = await client.scroll(
                collection_name=settings.qdrant_collection,
                limit=SCROLL_BATCH_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
                scroll_filter=scroll_filter,
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
            "bm25 corpus scroll failed against %s (tenant=%s): %s",
            settings.qdrant_collection,
            tenant_slug,
            exc,
        )
    return chunks


async def build_corpus(
    tenant_slug: str | None = None,
) -> BM25Corpus | None:
    """Rebuild the in-memory BM25 index for ``tenant_slug`` from Qdrant.

    Per-tenant corpus — each tenant gets its own ``BM25Okapi`` instance so
    BM25 idf statistics are computed over the tenant's own chunks instead
    of the global mix. The cache is keyed by slug.
    """

    chunks = await _scroll_corpus(tenant_slug)
    chunks = [c for c in chunks if c.text]
    if not chunks:
        _corpora.pop(tenant_slug, None)
        return None

    tokens = [tokenize(c.text) for c in chunks]
    index = BM25Okapi(tokens)
    corpus = BM25Corpus(
        built_at=time.time(), index=index, chunks=chunks, tokens=tokens
    )
    _corpora[tenant_slug] = corpus
    _log.info(
        "bm25 corpus rebuilt: tenant=%s chunks=%d", tenant_slug, len(chunks)
    )
    return corpus


async def get_corpus(
    tenant_slug: str | None = None,
) -> BM25Corpus | None:
    cached = _corpora.get(tenant_slug)
    if cached is not None and cached.is_fresh():
        return cached
    return await build_corpus(tenant_slug)


def clear_corpus() -> None:
    """Test hook — drop every cached corpus (all tenants)."""

    _corpora.clear()


async def sparse_search(
    query: str,
    *,
    k: int = 50,
    filters: Filter | None = None,
) -> list[ScoredChunk]:
    """Score the per-tenant corpus against the query and return the top-``k``.

    ``filters`` carries the Qdrant ``Filter`` produced by the retrieval
    node. We extract the ``tenant_id`` ``MatchValue`` from it to pick the
    right per-tenant corpus. Other predicates (file path, folder, etc.)
    are intentionally NOT honoured here — BM25 doesn't index payload, so
    a richer filter would silently be ignored and produce results outside
    the caller's intent. Today only the tenant predicate is required.

    Returns an empty list if the corpus is empty or cannot be built. Never
    raises so the orchestrator can rely on the dense arm in degraded mode.
    """

    if not query.strip():
        return []

    tenant_slug = _extract_tenant_slug(filters)
    corpus = await get_corpus(tenant_slug)
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


def _extract_tenant_slug(filters: Filter | None) -> str | None:
    """Pull the ``tenant_id`` slug out of a Qdrant ``Filter``.

    The retrieval nodes build the filter as
    ``Filter(must=[FieldCondition(key='tenant_id', match=MatchValue(value=<slug>))])``,
    so we walk ``filter.must`` looking for that shape. Returns ``None`` if
    no tenant predicate is present — the caller then operates on the
    legacy "all tenants" corpus (test/diagnostics only)."""

    if filters is None:
        return None
    must = getattr(filters, "must", None) or []
    for condition in must:
        if not isinstance(condition, FieldCondition):
            continue
        if condition.key != "tenant_id":
            continue
        match = getattr(condition, "match", None)
        value = getattr(match, "value", None)
        if isinstance(value, str):
            return value
    return None
