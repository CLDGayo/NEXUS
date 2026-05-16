"""Cross-encoder reranker.

Takes the top-50 candidates emerging from RRF and reorders them by a true
``CrossEncoder(query, chunk)`` score. We use ``fastembed.TextCrossEncoder``
so the runtime stays ONNX-only (no torch in the image). Default model is
``jinaai/jina-reranker-v2-base-multilingual`` per the v2 architecture brief.

The model loads lazily on first call. In tests, monkey-patch ``rerank``
to bypass the encoder entirely.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from rag.config import settings
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_cross_encoder():
    """Memoized lazy-loaded cross-encoder. Imported here to defer the
    fastembed model download until the first real rerank call."""

    from fastembed import TextCrossEncoder

    return TextCrossEncoder(model_name=settings.rerank_model)


def _score_sync(query: str, texts: list[str]) -> list[float]:
    encoder = get_cross_encoder()
    # fastembed returns a generator of numpy floats.
    return [float(score) for score in encoder.rerank(query, texts)]


async def rerank(
    query: str,
    candidates: list[ScoredChunk],
    *,
    top_k: int = 8,
) -> list[ScoredChunk]:
    """Reorder ``candidates`` by cross-encoder relevance and keep top ``top_k``.

    Falls back to returning the head of the input list (already RRF-ranked)
    if the encoder cannot be loaded or invocation fails.
    """

    if not candidates:
        return []
    if top_k <= 0:
        return []

    texts = [c.text for c in candidates]
    try:
        scores = await asyncio.to_thread(_score_sync, query, texts)
    except Exception as exc:
        _log.warning("rerank failed; falling back to RRF order: %s", exc)
        return candidates[:top_k]

    scored = [c.with_score(s) for c, s in zip(candidates, scores)]
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_k]
