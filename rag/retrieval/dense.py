"""Dense retrieval arm — query Qdrant with a fastembed-encoded query vector.

Phase 3 queries the existing v1 collection (``nexus-vault``) using
``BAAI/bge-small-en-v1.5`` so live data is reachable today. Phase 2's
``ingest_v2`` pipeline will produce ``nexus-vault-v2`` with jina-v2 late
chunking; flip ``QDRANT_COLLECTION`` + ``EMBED_MODEL`` to switch backends.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient

from rag.config import settings
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


@lru_cache(maxsize=1)
def get_embedder() -> TextEmbedding:
    """Memoized fastembed text encoder. Cold start downloads the ONNX model."""

    return TextEmbedding(model_name=settings.embed_model)


def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
    return _client


def _encode_query(query: str) -> list[float]:
    embedder = get_embedder()
    # fastembed returns a generator over numpy arrays.
    vector = next(iter(embedder.query_embed([query])))
    return vector.tolist()


def embed_text(text: str) -> list[float]:
    """Encode ``text`` as a passage embedding for storage.

    Phase 32 — product catalog uses the same fastembed encoder as the
    live retrieval arm so product vectors land in the same dim/space the
    customer query is encoded with. Uses ``embed`` (passage mode) rather
    than ``query_embed`` so the asymmetric-encoder semantics line up:
    products are stored as documents, customer DMs are stored as queries.
    """

    if not text or not text.strip():
        raise ValueError("embed_text requires a non-empty string")
    embedder = get_embedder()
    vector = next(iter(embedder.embed([text])))
    return vector.tolist()


def _chunk_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in ("text", "content", "chunk_text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def dense_search(
    query: str,
    *,
    k: int = 50,
    filters: dict[str, Any] | None = None,
) -> list[ScoredChunk]:
    """Run a single dense query against the configured Qdrant collection.

    Returns up to ``k`` results ranked by cosine similarity. ``filters`` is
    forwarded as a Qdrant ``Filter`` payload-compat dict; pass ``None`` to
    skip filtering. An empty list is returned if the collection is empty,
    missing, or unreachable — never raises.
    """

    if not query.strip():
        return []

    client = get_qdrant_client()
    try:
        vector = _encode_query(query)
    except Exception as exc:  # pragma: no cover - fastembed cold-start failure
        _log.error("query embed failed: %s", exc)
        return []

    try:
        response = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=k,
            with_payload=True,
            query_filter=filters,
        )
    except Exception as exc:
        _log.warning(
            "dense search failed against %s: %s", settings.qdrant_collection, exc
        )
        return []

    hits: list[ScoredChunk] = []
    for point in response.points:
        payload = dict(point.payload or {})
        hits.append(
            ScoredChunk(
                id=str(point.id),
                text=_chunk_text(payload),
                score=float(point.score),
                metadata=payload,
            )
        )
    return hits
