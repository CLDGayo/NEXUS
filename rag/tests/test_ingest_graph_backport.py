"""Phase 23 — v1 ingest graph backport.

The v1 ``rag/ingest.py`` pipeline must populate the v2 ``vault_notes`` +
``vault_links`` SQLite graph DB so the orchestrator's ``retrieve_graph``
arm has data to expand over. ``wikilinks_in`` is computed on-the-fly at
retrieval time via ``neighbors_of`` (forward + reverse), so the only
thing the ingest path is responsible for is recording outbound edges +
running the resolver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ingest as ingest_module
from ingest_v2.graph_db import all_links, connect, neighbors_of


def _seed_vault(root: Path) -> tuple[Path, Path, Path]:
    """Two notes that link to each other plus one outbound to an unknown
    target. Returns ``(note_a, note_b, note_c)`` paths."""

    root.mkdir(parents=True, exist_ok=True)
    note_a = root / "Note A.md"
    note_a.write_text(
        """---
title: Note A
---
This note refers to [[Note B]] for the canonical write-up
and also mentions [[Nonexistent Note]] which has no file.
""",
        encoding="utf-8",
    )
    note_b = root / "Note B.md"
    note_b.write_text(
        """---
title: Note B
aliases: [Beta Note]
---
Canonical reference linking back to [[Note A]] from inside the body.
""",
        encoding="utf-8",
    )
    note_c = root / "Note C.md"
    note_c.write_text(
        """---
title: Note C
---
Standalone with no outbound links.
""",
        encoding="utf-8",
    )
    return note_a, note_b, note_c


@pytest.mark.integration
async def test_index_graph_populates_notes_and_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    note_a, note_b, note_c = _seed_vault(vault)

    graph_db = tmp_path / "graph.db"
    monkeypatch.setenv("NEXUS_GRAPH_DB", str(graph_db))
    monkeypatch.setattr(ingest_module, "VAULT_PATH", vault, raising=False)

    notes, _ = await ingest_module._index_graph_for_files(
        [note_a, note_b, note_c]
    )

    assert notes == 3

    async with connect() as conn:
        # Forward + reverse neighbor lookup is what ``retrieve_graph``
        # uses. Confirm both directions resolved.
        a_neighbors = await neighbors_of(conn, "Note A.md")
        b_neighbors = await neighbors_of(conn, "Note B.md")
        c_neighbors = await neighbors_of(conn, "Note C.md")

        assert "Note B.md" in a_neighbors
        assert "Note A.md" in b_neighbors
        assert c_neighbors == ()

        rows = await all_links(conn)
        # Unresolved edge to Nonexistent is still recorded for forensics.
        a_out = [r for r in rows if r["src_path"] == "Note A.md"]
        targets = {r["dst_target"] for r in a_out}
        assert "Note B" in targets
        assert "Nonexistent Note" in targets

        # Resolved-vs-unresolved invariant: known targets get a dst_path,
        # the dangling [[Nonexistent Note]] keeps dst_path = None.
        resolved_for_a = {
            r["dst_target"]: r["dst_path"] for r in a_out
        }
        assert resolved_for_a["Note B"] == "Note B.md"
        assert resolved_for_a["Nonexistent Note"] is None


@pytest.mark.integration
async def test_index_graph_empty_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input must short-circuit — no DB touched, no exception."""

    monkeypatch.setenv("NEXUS_GRAPH_DB", str(tmp_path / "graph.db"))
    monkeypatch.setattr(ingest_module, "VAULT_PATH", tmp_path, raising=False)
    notes, resolved = await ingest_module._index_graph_for_files([])
    assert notes == 0
    assert resolved == 0


@pytest.mark.integration
async def test_index_graph_skips_unparseable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files that fail ``frontmatter.load`` must be skipped silently.

    The Qdrant arm already skips the same files (``chunks_from_file``
    returns ``[]`` on parse failure), so the graph stays consistent
    with the vector store.
    """

    vault = tmp_path / "vault"
    vault.mkdir()
    good = vault / "Good.md"
    good.write_text("---\ntitle: Good\n---\nlinks to [[Other]]", encoding="utf-8")
    # Path to a file that does not exist — frontmatter.load raises.
    missing = vault / "Missing.md"

    monkeypatch.setenv("NEXUS_GRAPH_DB", str(tmp_path / "graph.db"))
    monkeypatch.setattr(ingest_module, "VAULT_PATH", vault, raising=False)

    notes, _ = await ingest_module._index_graph_for_files([good, missing])
    assert notes == 1
