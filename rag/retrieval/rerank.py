"""Cross-encoder reranker.

Takes the top-50 candidates emerging from RRF and reorders them by a true
``CrossEncoder(query, chunk)`` score. We use ``fastembed``'s ONNX
``TextCrossEncoder`` so the runtime stays ONNX-only (no torch in the image).
Default model is ``jinaai/jina-reranker-v2-base-multilingual`` per the v2
architecture brief.

The model loads lazily on first call. In tests, monkey-patch ``rerank``
to bypass the encoder entirely.

Import-path note (2026-05-21): ``fastembed`` >=0.4 moved ``TextCrossEncoder``
under ``fastembed.rerank.cross_encoder``. Older versions exposed it at the
top level. ``_load_cross_encoder_cls()`` tries the new path first and falls
back to the legacy path, raising a single clean error if both fail so the
next dep drift is obvious in logs instead of buried in a generic
"rerank failed" warning.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

from rag.config import settings
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)


def _load_cross_encoder_cls() -> Any:
    """Resolve the ``TextCrossEncoder`` class across fastembed versions.

    Raises ``ImportError`` with a single clean message if neither path
    resolves, so log readers see *one* line, not a generic exception.
    """

    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder
    except ImportError:
        pass
    try:
        from fastembed import TextCrossEncoder  # type: ignore[attr-defined,no-redef]

        return TextCrossEncoder
    except ImportError as exc:
        raise ImportError(
            "fastembed.TextCrossEncoder unavailable at "
            "`fastembed.rerank.cross_encoder` (>=0.4) or top-level (<0.4). "
            "Pin `fastembed` directly in pyproject.toml — relying on "
            "qdrant-client[fastembed]'s transitive pin caused a silent "
            "reranker outage on 2026-05-21."
        ) from exc


@lru_cache(maxsize=1)
def get_cross_encoder():
    """Memoized lazy-loaded cross-encoder. Imported here to defer the
    fastembed model download until the first real rerank call.

    Passes ``cache_dir`` explicitly so the ONNX weights persist across
    container restarts on the mounted ``fastembed_cache`` volume.
    """

    from pathlib import Path

    cls = _load_cross_encoder_cls()
    cache_dir = Path(settings.fastembed_cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.warning("could not create fastembed cache dir %s: %s", cache_dir, exc)
    return cls(model_name=settings.rerank_model, cache_dir=str(cache_dir))


def reranker_import_probe() -> dict[str, Any]:
    """Cheap health check: confirms the class resolves without loading the
    model weights. Used by the ``/health/reranker`` endpoint and CI.
    """

    try:
        cls = _load_cross_encoder_cls()
    except ImportError as exc:
        return {"ok": False, "error": str(exc), "model": settings.rerank_model}
    return {
        "ok": True,
        "import_path": f"{cls.__module__}.{cls.__qualname__}",
        "model": settings.rerank_model,
    }


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
