"""Tests for the wikilink graph retriever arm."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingest_v2.graph_db import (
    connect,
    replace_links_for,
    resolve_link_targets,
    upsert_note,
)
from rag.retrieval import graph as graph_module
from rag.retrieval.types import ScoredChunk


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_GRAPH_DB", str(tmp_path / "graph.db"))
    yield


async def _seed_three_note_vault() -> None:
    """A → B, A → C, B → C. Used by the seed/neighbor tests below."""

    async with connect() as conn:
        await upsert_note(conn, path="/v/Alpha.md", title="Project Alpha", aliases=())
        await upsert_note(conn, path="/v/Beta.md", title="Project Beta", aliases=())
        await upsert_note(conn, path="/v/Gamma.md", title="Concept Gamma", aliases=())
        await replace_links_for(
            conn, src_path="/v/Alpha.md",
            links=(("Project Beta", None, None), ("Concept Gamma", None, None)),
        )
        await replace_links_for(
            conn, src_path="/v/Beta.md",
            links=(("Concept Gamma", None, None),),
        )
        await conn.commit()
        await resolve_link_targets(conn)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeedResolution:
    async def test_resolves_title_word(self, graph_db) -> None:
        await _seed_three_note_vault()
        async with connect() as conn:
            seeds = await graph_module._resolve_seeds(
                conn, query="tell me about alpha", limit=3
            )
        seed_paths = [p for p, _ in seeds]
        assert "/v/Alpha.md" in seed_paths

    async def test_no_match_returns_empty(self, graph_db) -> None:
        await _seed_three_note_vault()
        async with connect() as conn:
            seeds = await graph_module._resolve_seeds(
                conn, query="nothing related here", limit=3
            )
        assert seeds == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestGraphSearch:
    async def test_empty_query_returns_empty(self, graph_db) -> None:
        result = await graph_module.graph_search("", k=5)
        assert result == []

    async def test_no_seeds_returns_empty(self, graph_db) -> None:
        # DB is empty (autouse fixture only sets env path).
        result = await graph_module.graph_search("alpha", k=5)
        assert result == []

    async def test_walks_and_returns_qdrant_hits(
        self, graph_db, monkeypatch
    ) -> None:
        await _seed_three_note_vault()

        captured_paths: list[list[str]] = []

        async def fake_fetch(query: str, paths: list[str], k: int):
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

        monkeypatch.setattr(
            graph_module, "_fetch_chunks_by_files", fake_fetch
        )

        result = await graph_module.graph_search("tell me about alpha", k=5)
        # Seed = Alpha, neighbors = Beta + Gamma (one-hop). All three are
        # passed to Qdrant.
        assert captured_paths, "fetcher must be called"
        paths_seen = set(captured_paths[0])
        assert "/v/Alpha.md" in paths_seen
        assert "/v/Beta.md" in paths_seen
        assert "/v/Gamma.md" in paths_seen

        assert len(result) >= 1
        assert all(isinstance(c, ScoredChunk) for c in result)

    async def test_db_failure_returns_empty(
        self, graph_db, monkeypatch
    ) -> None:
        """If the SQLite path is corrupt we degrade — no exception."""

        def broken_connect(*a, **kw):
            # The real connect() returns an async context manager. Raising
            # at call time lets the module's try/except catch us before
            # any `async with` machinery spins up.
            raise RuntimeError("disk gone")

        monkeypatch.setattr(graph_module, "connect", broken_connect)
        result = await graph_module.graph_search("alpha", k=5)
        assert result == []
