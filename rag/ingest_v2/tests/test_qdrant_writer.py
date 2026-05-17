"""Phase 4 Qdrant writer tests.

Mocks ``AsyncQdrantClient`` so unit tests do not touch a live Qdrant.
Covers payload serialization shape, collection init idempotence, and batch
upsert behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rag.ingest_v2 import qdrant_writer
from rag.ingest_v2.qdrant_writer import (
    _serialize_payload,
    init_collection,
    upsert_chunks,
)
from rag.ingest_v2.types import IngestChunk


def _chunk(i: int) -> IngestChunk:
    return IngestChunk(
        id=f"chunk-{i:08x}",
        text=f"text body {i}",
        embedding=tuple([float(i)] * 4),
        metadata={"file": "/vault/note.md", "chunk_index": i, "chunk_total": 3},
    )


class _MockClient:
    """Mimics the small subset of AsyncQdrantClient we use."""

    def __init__(self, *, exists: bool = False) -> None:
        self.exists_value = exists
        self.collection_exists = AsyncMock(return_value=exists)
        self.create_collection = AsyncMock()
        self.delete_collection = AsyncMock()
        self.upsert = AsyncMock()


@pytest.fixture
def mock_client() -> _MockClient:
    client = _MockClient(exists=False)
    qdrant_writer.set_client(client)  # type: ignore[arg-type]
    try:
        yield client
    finally:
        qdrant_writer.set_client(None)


# ---------------------------------------------------------------------------
# Payload serialization
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPayload:
    def test_includes_text_under_text_key(self) -> None:
        chunk = _chunk(0)
        payload = _serialize_payload(chunk)
        assert payload["text"] == "text body 0"

    def test_metadata_fields_present(self) -> None:
        chunk = _chunk(2)
        payload = _serialize_payload(chunk)
        assert payload["file"] == "/vault/note.md"
        assert payload["chunk_index"] == 2
        assert payload["chunk_total"] == 3


# ---------------------------------------------------------------------------
# init_collection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitCollection:
    async def test_creates_when_missing(self, mock_client: _MockClient) -> None:
        name = await init_collection(collection="nexus-vault-v2", vector_size=8)
        assert name == "nexus-vault-v2"
        mock_client.create_collection.assert_awaited_once()
        call_kwargs = mock_client.create_collection.await_args.kwargs
        assert call_kwargs["collection_name"] == "nexus-vault-v2"
        assert call_kwargs["vectors_config"].size == 8

    async def test_idempotent_when_exists(self, mock_client: _MockClient) -> None:
        mock_client.collection_exists = AsyncMock(return_value=True)
        await init_collection(collection="nexus-vault-v2")
        mock_client.create_collection.assert_not_awaited()
        mock_client.delete_collection.assert_not_awaited()

    async def test_recreate_drops_then_creates(self, mock_client: _MockClient) -> None:
        mock_client.collection_exists = AsyncMock(return_value=True)
        await init_collection(collection="nexus-vault-v2", recreate=True)
        mock_client.delete_collection.assert_awaited_once()
        mock_client.create_collection.assert_awaited_once()


# ---------------------------------------------------------------------------
# upsert_chunks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUpsert:
    async def test_empty_input_no_calls(self, mock_client: _MockClient) -> None:
        result = await upsert_chunks([])
        assert result == 0
        mock_client.upsert.assert_not_awaited()

    async def test_writes_all_chunks(self, mock_client: _MockClient) -> None:
        chunks = [_chunk(i) for i in range(5)]
        result = await upsert_chunks(chunks, collection="nexus-vault-v2", batch_size=2)
        assert result == 5
        # ceil(5/2) = 3 batches
        assert mock_client.upsert.await_count == 3

    async def test_uses_default_collection(self, mock_client: _MockClient) -> None:
        await upsert_chunks([_chunk(0)])
        call = mock_client.upsert.await_args
        assert call.kwargs["collection_name"]  # whatever settings default is
        assert len(call.kwargs["points"]) == 1
        point = call.kwargs["points"][0]
        assert point.id == "chunk-00000000"
        assert point.vector == [0.0, 0.0, 0.0, 0.0]
        assert point.payload["text"] == "text body 0"
