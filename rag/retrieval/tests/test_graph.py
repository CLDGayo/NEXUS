"""Tests for the wikilink graph retriever arm (Phase 31+).

Migration note (old → new API):
  - upsert_note(conn, path, title, aliases) removed; replaced by
    upsert_document(session, tenant_id=..., file=..., title=..., aliases=(...)).
  - replace_links_for now takes src_document_id (UUID) not src_path.
  - All graph_db helpers require tenant_id= kwarg.
  - connect() yields an AsyncSession; no manual .commit() calls needed.
  - graph_search() already accepted tenant_id (str) — callers pass a UUID str.
  - Tests that seed the graph now require a live Postgres connection and are
    skipped when DATABASE_URL is absent.  The monkeypatch for connect() in
    test_db_failure_returns_empty still works without Postgres because it
    patches before any real connection is made.
"""

from __future__ import annotations

import os
import uuid

import pytest

from rag.ingest_v2.graph_db import (
    connect,
    replace_links_for,
    resolve_link_targets,
    upsert_document,
)
from rag.retrieval import graph as graph_module
from rag.retrieval.types import ScoredChunk

_DB_AVAILABLE = bool(os.getenv("DATABASE_URL"))

# Tenant used by seeding helpers — unique per test-session invocation.
_TENANT_ID = uuid.uuid4()
_TENANT_STR = str(_TENANT_ID)


async def _seed_three_note_vault(tenant_id: uuid.UUID) -> None:
    """Seed: Alpha → Beta, Alpha → Gamma, Beta → Gamma.

    Used by seed/neighbor tests that need a live Postgres connection.
    """
    async with connect() as session:
        id_alpha = await upsert_document(
            session, tenant_id=tenant_id,
            file="/v/Alpha.md", title="Project Alpha",
        )
        id_beta = await upsert_document(
            session, tenant_id=tenant_id,
            file="/v/Beta.md", title="Project Beta",
        )
        id_gamma = await upsert_document(
            session, tenant_id=tenant_id,
            file="/v/Gamma.md", title="Concept Gamma",
        )
        await replace_links_for(
            session,
            tenant_id=tenant_id,
            src_document_id=id_alpha,
            links=(("Project Beta", None, None), ("Concept Gamma", None, None)),
        )
        await replace_links_for(
            session,
            tenant_id=tenant_id,
            src_document_id=id_beta,
            links=(("Concept Gamma", None, None),),
        )
        await resolve_link_targets(session, tenant_id=tenant_id)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeedResolution:
    @pytest.mark.skipif(not _DB_AVAILABLE, reason="Postgres DATABASE_URL not set")
    async def test_resolves_title_word(self) -> None:
        tenant = uuid.uuid4()
        await _seed_three_note_vault(tenant)
        async with connect() as session:
            seeds = await graph_module._resolve_seeds(
                session, query="tell me about alpha", limit=3,
                tenant_id=tenant,
            )
        seed_paths = [p for p, _ in seeds]
        assert "/v/Alpha.md" in seed_paths

    @pytest.mark.skipif(not _DB_AVAILABLE, reason="Postgres DATABASE_URL not set")
    async def test_no_match_returns_empty(self) -> None:
        tenant = uuid.uuid4()
        await _seed_three_note_vault(tenant)
        async with connect() as session:
            seeds = await graph_module._resolve_seeds(
                session, query="nothing related here", limit=3,
                tenant_id=tenant,
            )
        assert seeds == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestGraphSearch:
    async def test_empty_query_returns_empty(self) -> None:
        result = await graph_module.graph_search("", k=5, tenant_id=_TENANT_STR)
        assert result == []

    @pytest.mark.skipif(not _DB_AVAILABLE, reason="Postgres DATABASE_URL not set")
    async def test_no_seeds_returns_empty(self) -> None:
        # Fresh tenant — DB has no documents for it.
        fresh = str(uuid.uuid4())
        result = await graph_module.graph_search("alpha", k=5, tenant_id=fresh)
        assert result == []

    @pytest.mark.skipif(not _DB_AVAILABLE, reason="Postgres DATABASE_URL not set")
    async def test_walks_and_returns_qdrant_hits(self, monkeypatch) -> None:
        tenant = uuid.uuid4()
        await _seed_three_note_vault(tenant)

        captured_paths: list[list[str]] = []

        async def fake_fetch(query: str, paths: list[str], k: int, **_kwargs):
            captured_paths.append(list(paths))
            return [
                ScoredChunk(
                    id=f"chunk-{i}",
                    text=f"chunk text {p}",
                    score=0.9 - 0.1 * i,
                    metadata={"file": p},
                )
                for i, p in enumerate(paths[:k])
            ]

        monkeypatch.setattr(graph_module, "_fetch_chunks_by_files", fake_fetch)

        result = await graph_module.graph_search(
            "tell me about alpha", k=5, tenant_id=str(tenant)
        )
        # Seed = Alpha, neighbors = Beta + Gamma (one-hop). All three passed to Qdrant.
        assert captured_paths, "fetcher must be called"
        paths_seen = set(captured_paths[0])
        assert "/v/Alpha.md" in paths_seen
        assert "/v/Beta.md" in paths_seen
        assert "/v/Gamma.md" in paths_seen

        assert len(result) >= 1
        assert all(isinstance(c, ScoredChunk) for c in result)

    async def test_db_failure_returns_empty(self, monkeypatch) -> None:
        """If the Postgres session raises we degrade gracefully — no exception."""

        def broken_connect(*a, **kw):
            # Raise at call time so the module's try/except catches it
            # before any async-with machinery spins up.
            raise RuntimeError("disk gone")

        monkeypatch.setattr(graph_module, "connect", broken_connect)
        result = await graph_module.graph_search("alpha", k=5, tenant_id=_TENANT_STR)
        assert result == []
