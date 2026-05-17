"""Tests for the wikilink graph builder that runs at ingestion time."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingest_v2.graph_db import (
    all_links,
    connect,
    fetch_note_titles,
    resolve_link_targets,
)
from rag.ingest_v2.graph_index import index_file_links


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    db_path = tmp_path / "graph.db"
    monkeypatch.setenv("NEXUS_GRAPH_DB", str(db_path))
    yield db_path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_vault_pass_resolves_links(graph_db) -> None:
    """A → B, A → C, B → C with three real wikilinks should resolve.

    Mirrors the fixture spec called out in the plan: small three-note
    vault establishing forward + transitive coverage.
    """

    notes = {
        "/v/A.md": (
            "A",
            (),
            "intro text linking to [[B]] and [[C|the C note]]",
        ),
        "/v/B.md": (
            "B",
            ("Beta",),
            "this links to [[C]] and to [[A#header]]",
        ),
        "/v/C.md": ("C", (), "no outbound links here"),
    }

    async with connect() as conn:
        for path, (title, aliases, body) in notes.items():
            frontmatter = {"title": title, "aliases": list(aliases)} if aliases else {}
            await index_file_links(
                conn,
                path=Path(path),
                body=body,
                frontmatter=frontmatter or {"title": title},
            )
        await resolve_link_targets(conn)

        titles = {p: (t, aliases) for p, t, aliases in await fetch_note_titles(conn)}
        assert titles["/v/A.md"][0] == "A"
        assert titles["/v/B.md"][0] == "B"

        links = await all_links(conn)
        by_src: dict[str, dict[str, str | None]] = {}
        for link in links:
            by_src.setdefault(link["src_path"], {})[link["dst_target"]] = link[
                "dst_path"
            ]

        assert by_src["/v/A.md"]["B"] == "/v/B.md"
        assert by_src["/v/A.md"]["C"] == "/v/C.md"
        # B has both [[C]] and [[A#header]]; the anchor variant must
        # resolve to A by title.
        assert by_src["/v/B.md"]["C"] == "/v/C.md"
        assert by_src["/v/B.md"]["A"] == "/v/A.md"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_alias_pickup(graph_db) -> None:
    async with connect() as conn:
        await index_file_links(
            conn,
            path=Path("/v/Alpha.md"),
            body="seed note",
            frontmatter={"title": "Project Alpha", "aliases": ["Alpha", "PA"]},
        )
        await index_file_links(
            conn,
            path=Path("/v/Other.md"),
            body="see [[PA]] for context",
            frontmatter={"title": "Other"},
        )
        await resolve_link_targets(conn)

        links = await all_links(conn)
        pa_link = next(l for l in links if l["dst_target"] == "PA")
        assert pa_link["dst_path"] == "/v/Alpha.md"
