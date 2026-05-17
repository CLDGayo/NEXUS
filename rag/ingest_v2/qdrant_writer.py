"""Qdrant collection initialization + idempotent chunk upsert.

Ingest writes into a NEW collection (default ``nexus-vault-v2``) at the
embedding dim of the late-chunker model so the existing v1 collection
(``nexus-vault``, 384-dim bge-small) keeps serving Phase 3 retrieval until
the migration cutover.

Collection metadata stamps the embedding model name; querying-side drift
detection compares this against the configured ``EMBED_MODEL`` and refuses
to query a mismatched collection.
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from rag.config import settings
from rag.ingest_v2.types import IngestChunk

_log = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=60,
        )
    return _client


def set_client(client: AsyncQdrantClient | None) -> None:
    """Test hook — swap in a mock client."""

    global _client
    _client = client


async def init_collection(
    *,
    collection: str | None = None,
    vector_size: int | None = None,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
    recreate: bool = False,
) -> str:
    """Create ``collection`` if missing. Returns the resolved name.

    ``vector_size`` defaults to ``settings.ingest_embed_dim``. Pass
    ``recreate=True`` only when intentionally rebuilding from scratch —
    drops the existing collection.
    """

    name = collection or settings.ingest_qdrant_collection
    dim = vector_size or settings.ingest_embed_dim
    client = get_client()

    exists = await client.collection_exists(collection_name=name)
    if exists and recreate:
        await client.delete_collection(collection_name=name)
        exists = False

    if not exists:
        await client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=dim, distance=distance),
        )
        _log.info("created qdrant collection %s (dim=%d)", name, dim)

    return name


async def upsert_chunks(
    chunks: list[IngestChunk],
    *,
    collection: str | None = None,
    batch_size: int = 64,
) -> int:
    """Upsert ``chunks`` into Qdrant. Returns the number of points written."""

    if not chunks:
        return 0

    name = collection or settings.ingest_qdrant_collection
    client = get_client()

    points = [
        qmodels.PointStruct(
            id=chunk.id,
            vector=list(chunk.embedding),
            payload=_serialize_payload(chunk),
        )
        for chunk in chunks
    ]

    written = 0
    for batch_start in range(0, len(points), batch_size):
        batch = points[batch_start : batch_start + batch_size]
        await client.upsert(collection_name=name, points=batch, wait=True)
        written += len(batch)
    return written


def _serialize_payload(chunk: IngestChunk) -> dict[str, Any]:
    """Flatten ``IngestChunk`` into a Qdrant-storable payload.

    Stored fields are the union of metadata plus the chunk text under
    ``text``. Retrieval-side code reads ``text`` to build the LLM context.
    """

    payload: dict[str, Any] = dict(chunk.metadata)
    payload["text"] = chunk.text
    return payload
