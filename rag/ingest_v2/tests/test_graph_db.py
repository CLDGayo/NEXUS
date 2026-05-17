"""Tests for the SQLite vault-link graph layer."""

from __future__ import annotations

import os

import pytest

from rag.ingest_v2.graph_db import (
    all_links,
    connect,
    fetch_note_titles,
    neighbors_of,
    replace_links_for,
    resolve_link_targets,
    upsert_note,
)


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    """Isolate each test in its own SQLite file."""

    db_path = tmp_path / "graph.db"
    monkeypatch.setenv("NEXUS_GRAPH_DB", str(db_path))
    yield db_path
    # tmp_path cleanup is automatic.
    monkeypatch.delenv("NEXUS_GRAPH_DB", raising=False)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSchema:
    async def test_init_idempotent(self, graph_db) -> None:
        async with connect() as conn:
            pass
        async with connect() as conn:
            # Reopen — schema still intact, no error.
            rows = await conn.execute_fetchall("SELECT count(*) FROM vault_notes")
            assert rows[0][0] == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestUpsertAndLinks:
    async def test_upsert_note_and_links(self, graph_db) -> None:
        async with connect() as conn:
            await upsert_note(
                conn,
                path="/vault/Projects/Alpha.md",
                title="Project Alpha",
                aliases=("Alpha", "PA"),
            )
            await replace_links_for(
                conn,
                src_path="/vault/Projects/Alpha.md",
                links=(
                    ("Project Beta", None, None),
                    ("Project Beta", "Tasks", None),
                    ("Concept X", None, "the x note"),
                ),
            )
            await conn.commit()

            links = await all_links(conn)
            assert len(links) == 3

            titles = await fetch_note_titles(conn)
            assert ("/vault/Projects/Alpha.md", "Project Alpha", ("Alpha", "PA")) in titles

    async def test_replace_overwrites(self, graph_db) -> None:
        async with connect() as conn:
            await replace_links_for(
                conn,
                src_path="/v/a.md",
                links=(("B", None, None), ("C", None, None)),
            )
            await replace_links_for(
                conn,
                src_path="/v/a.md",
                links=(("D", None, None),),
            )
            await conn.commit()

            links = await all_links(conn)
            targets = {l["dst_target"] for l in links}
            assert targets == {"D"}

    async def test_replace_dedups_duplicate_target_anchor(self, graph_db) -> None:
        async with connect() as conn:
            await replace_links_for(
                conn,
                src_path="/v/a.md",
                links=(
                    ("B", "Section1", None),
                    ("B", "Section1", None),  # duplicate (target, anchor)
                    ("B", "Section2", None),  # different anchor → distinct row
                ),
            )
            await conn.commit()

            links = await all_links(conn)
            anchors = sorted(l["anchor"] for l in links)
            assert anchors == ["Section1", "Section2"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestResolveTargets:
    async def test_resolves_titles(self, graph_db) -> None:
        async with connect() as conn:
            await upsert_note(conn, path="/v/A.md", title="A", aliases=())
            await upsert_note(conn, path="/v/B.md", title="B", aliases=())
            await upsert_note(conn, path="/v/C.md", title="C", aliases=())
            await replace_links_for(
                conn,
                src_path="/v/A.md",
                links=(("B", None, None), ("C", None, None)),
            )
            await replace_links_for(
                conn,
                src_path="/v/B.md",
                links=(("C", None, None),),
            )
            await conn.commit()

            resolved = await resolve_link_targets(conn)
            assert resolved == 3

            links = await all_links(conn)
            by_src: dict[str, set] = {}
            for link in links:
                by_src.setdefault(link["src_path"], set()).add(link["dst_path"])
            assert by_src["/v/A.md"] == {"/v/B.md", "/v/C.md"}
            assert by_src["/v/B.md"] == {"/v/C.md"}

    async def test_resolves_aliases(self, graph_db) -> None:
        async with connect() as conn:
            await upsert_note(
                conn, path="/v/Alpha.md", title="Project Alpha",
                aliases=("Alpha", "PA"),
            )
            await upsert_note(
                conn, path="/v/Beta.md", title="Project Beta", aliases=("PB",),
            )
            await replace_links_for(
                conn,
                src_path="/v/Beta.md",
                links=(("PA", None, None),),  # alias of Alpha
            )
            await conn.commit()

            await resolve_link_targets(conn)
            links = await all_links(conn)
            assert links[0]["dst_path"] == "/v/Alpha.md"

    async def test_unresolved_stays_null(self, graph_db) -> None:
        async with connect() as conn:
            await upsert_note(conn, path="/v/A.md", title="A", aliases=())
            await replace_links_for(
                conn, src_path="/v/A.md",
                links=(("Nonexistent", None, None),),
            )
            await conn.commit()
            await resolve_link_targets(conn)
            links = await all_links(conn)
            assert links[0]["dst_path"] is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestNeighbors:
    async def test_one_hop_forward_and_reverse(self, graph_db) -> None:
        async with connect() as conn:
            for path, title in [
                ("/v/A.md", "A"), ("/v/B.md", "B"), ("/v/C.md", "C"),
            ]:
                await upsert_note(conn, path=path, title=title, aliases=())
            await replace_links_for(
                conn, src_path="/v/A.md",
                links=(("B", None, None), ("C", None, None)),
            )
            await replace_links_for(
                conn, src_path="/v/B.md",
                links=(("C", None, None),),
            )
            await conn.commit()
            await resolve_link_targets(conn)

            # A → B, A → C, B → C. Neighbors of C = {A, B} (both reverse).
            n_c = set(await neighbors_of(conn, "/v/C.md"))
            assert n_c == {"/v/A.md", "/v/B.md"}

            # Neighbors of B = forward {C} + reverse {A}.
            n_b = set(await neighbors_of(conn, "/v/B.md"))
            assert n_b == {"/v/A.md", "/v/C.md"}
