"""Unit tests for the synchronized soft-delete + vault reconciliation endpoints.

Run from the rag/ directory:
    uv run --with pytest pytest tests/test_documents_archive.py -v
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest
from fastapi import HTTPException


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a tiny PARA vault, point env vars at it, and reload affected modules.

    The fixture yields ``(vault_root, documents_module)`` so each test gets a
    freshly-imported ``documents`` router with its module-level VAULT_PATH
    pointing at ``tmp_path``.
    """
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    for folder in ("00 - Inbox", "06 - Concepts", "04 - Archive"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)

    (tmp_path / "00 - Inbox" / "alpha.md").write_text("# alpha\n", encoding="utf-8")
    (tmp_path / "06 - Concepts" / "beta.md").write_text("# beta\n", encoding="utf-8")

    import inbox as _inbox
    importlib.reload(_inbox)
    from routers import documents as _documents
    importlib.reload(_documents)

    yield tmp_path, _documents


# ── _resolve_inside_vault ─────────────────────────────────────────────────

def test_resolve_inside_vault_accepts_normal_relative_path(tmp_vault):
    root, documents = tmp_vault
    p = documents._resolve_inside_vault("00 - Inbox/alpha.md", root)
    assert p == (root / "00 - Inbox" / "alpha.md").resolve()


def test_resolve_inside_vault_rejects_traversal(tmp_vault):
    _root, documents = tmp_vault
    with pytest.raises(HTTPException) as exc:
        documents._resolve_inside_vault("../etc/passwd", _root)
    assert exc.value.status_code == 400


def test_resolve_inside_vault_rejects_absolute(tmp_vault):
    _root, documents = tmp_vault
    with pytest.raises(HTTPException) as exc:
        documents._resolve_inside_vault("/etc/passwd", _root)
    assert exc.value.status_code == 400


def test_resolve_inside_vault_rejects_empty(tmp_vault):
    _root, documents = tmp_vault
    with pytest.raises(HTTPException):
        documents._resolve_inside_vault("", _root)


# ── _unique_path ──────────────────────────────────────────────────────────

def test_unique_path_returns_target_when_free(tmp_vault):
    root, documents = tmp_vault
    target = root / "fresh.md"
    assert documents._unique_path(target) == target


def test_unique_path_suffixes_on_collision(tmp_vault):
    root, documents = tmp_vault
    target = root / "exists.md"
    target.write_text("x", encoding="utf-8")
    out = documents._unique_path(target)
    assert out == root / "exists (2).md"

    out.write_text("y", encoding="utf-8")
    out2 = documents._unique_path(target)
    assert out2 == root / "exists (3).md"


# ── _archive_one ──────────────────────────────────────────────────────────

def test_archive_one_moves_file_preserving_folder(tmp_vault):
    root, documents = tmp_vault
    new_rel, orig_rel = documents._archive_one("00 - Inbox/alpha.md", root)

    assert orig_rel == "00 - Inbox/alpha.md"
    assert new_rel == "04 - Archive/00 - Inbox/alpha.md"
    assert (root / "04 - Archive" / "00 - Inbox" / "alpha.md").exists()
    assert not (root / "00 - Inbox" / "alpha.md").exists()


def test_archive_one_handles_collision_in_archive(tmp_vault):
    root, documents = tmp_vault
    # Pre-existing archived file with the same relative path.
    existing = root / "04 - Archive" / "00 - Inbox" / "alpha.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("old", encoding="utf-8")

    new_rel, _ = documents._archive_one("00 - Inbox/alpha.md", root)
    assert new_rel == "04 - Archive/00 - Inbox/alpha (2).md"
    assert (root / new_rel).exists()
    assert existing.exists()  # original archived copy untouched


def test_archive_one_idempotent_for_already_archived(tmp_vault):
    root, documents = tmp_vault
    archived = root / "04 - Archive" / "old.md"
    archived.write_text("# old\n", encoding="utf-8")

    new_rel, orig_rel = documents._archive_one("04 - Archive/old.md", root)
    assert new_rel == "04 - Archive/old.md"
    assert orig_rel == "04 - Archive/old.md"
    assert archived.exists()  # not moved


def test_archive_one_404_for_missing_file(tmp_vault):
    root, documents = tmp_vault
    with pytest.raises(HTTPException) as exc:
        documents._archive_one("00 - Inbox/does-not-exist.md", root)
    assert exc.value.status_code == 404


def test_archive_one_rejects_traversal(tmp_vault):
    root, documents = tmp_vault
    with pytest.raises(HTTPException) as exc:
        documents._archive_one("../escape.md", root)
    assert exc.value.status_code == 400


# ── archive_documents endpoint ────────────────────────────────────────────

def test_archive_documents_purges_vectors_for_each_path(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, documents = tmp_vault
    purged_paths: list[str] = []
    monkeypatch.setattr(
        documents,
        "delete_vectors_for_file",
        lambda rel: purged_paths.append(rel),
    )

    req = documents.ArchiveRequest(paths=[
        "00 - Inbox/alpha.md",
        "06 - Concepts/beta.md",
    ])
    res = asyncio.run(documents.archive_documents(req))

    assert len(res["archived"]) == 2
    assert res["failed"] == []
    assert res["vectors_purged"] == 2
    # Vector purge uses the ORIGINAL rel_path (matches Qdrant payload.file).
    assert sorted(purged_paths) == ["00 - Inbox/alpha.md", "06 - Concepts/beta.md"]
    assert (root / "04 - Archive" / "00 - Inbox" / "alpha.md").exists()
    assert (root / "04 - Archive" / "06 - Concepts" / "beta.md").exists()


def test_archive_documents_collects_per_item_failures(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault
    monkeypatch.setattr(documents, "delete_vectors_for_file", lambda _: None)

    req = documents.ArchiveRequest(paths=[
        "00 - Inbox/alpha.md",
        "00 - Inbox/missing.md",       # 404
        "../escape.md",                  # 400
    ])
    res = asyncio.run(documents.archive_documents(req))

    assert len(res["archived"]) == 1
    assert len(res["failed"]) == 2
    failed_paths = {f["path"] for f in res["failed"]}
    assert failed_paths == {"00 - Inbox/missing.md", "../escape.md"}


# ── reconcile_vault endpoint ──────────────────────────────────────────────

class _StubScrollClient:
    """Stand-in for QdrantClient.scroll — yields one page then signals done.

    Accepts either ``list[str]`` (just file names) or ``list[dict]`` payloads
    so tests can also exercise the index-summary path that needs ``text``.
    """
    def __init__(self, items) -> None:  # noqa: ANN001
        self._items = items

    def scroll(self, *, collection_name, limit, with_payload, with_vectors, offset):  # noqa: ANN001
        if offset is None:
            class _Pt:
                def __init__(self, payload):
                    self.payload = payload
            points = []
            for it in self._items:
                payload = {"file": it} if isinstance(it, str) else dict(it)
                points.append(_Pt(payload))
            return points, None
        return [], None


def test_reconcile_purges_only_orphans(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vault has alpha.md + beta.md; Qdrant claims alpha.md, beta.md, ghost.md."""
    _root, documents = tmp_vault
    qdrant_files = [
        "00 - Inbox/alpha.md",
        "06 - Concepts/beta.md",
        "06 - Concepts/ghost.md",  # orphan — never existed in vault
    ]
    monkeypatch.setattr(
        documents, "get_client", lambda: _StubScrollClient(qdrant_files)
    )
    purged: list[str] = []
    monkeypatch.setattr(
        documents, "delete_vectors_for_file", lambda rel: purged.append(rel)
    )

    res = asyncio.run(documents.reconcile_vault())

    assert res["qdrant_files"] == 3
    assert res["active_files"] == 2
    assert res["orphans"] == ["06 - Concepts/ghost.md"]
    assert res["purged"] == 1
    assert purged == ["06 - Concepts/ghost.md"]


def test_reconcile_no_orphans_when_in_sync(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault
    monkeypatch.setattr(
        documents,
        "get_client",
        lambda: _StubScrollClient(["00 - Inbox/alpha.md", "06 - Concepts/beta.md"]),
    )
    purged: list[str] = []
    monkeypatch.setattr(
        documents, "delete_vectors_for_file", lambda rel: purged.append(rel)
    )

    res = asyncio.run(documents.reconcile_vault())
    assert res["orphans"] == []
    assert res["purged"] == 0
    assert purged == []


def test_reconcile_502_when_qdrant_unreachable(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault

    def _boom():
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(documents, "get_client", _boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(documents.reconcile_vault())
    assert exc.value.status_code == 502


# ── index_summary endpoint ────────────────────────────────────────────────

def test_index_summary_aggregates_chunks_and_tokens(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault
    # Two chunks for alpha.md (200 + 400 chars → ~50 + 100 tokens),
    # one chunk for beta.md (16 chars → ~4 tokens).
    points = [
        {"file": "00 - Inbox/alpha.md", "text": "x" * 200},
        {"file": "00 - Inbox/alpha.md", "text": "y" * 400},
        {"file": "06 - Concepts/beta.md", "text": "z" * 16},
    ]
    monkeypatch.setattr(documents, "get_client", lambda: _StubScrollClient(points))

    res = asyncio.run(documents.index_summary())

    assert res["available"] is True
    assert res["total_chunks"] == 3
    assert res["summary"]["00 - Inbox/alpha.md"]["chunks"] == 2
    assert res["summary"]["00 - Inbox/alpha.md"]["est_tokens"] == 50 + 100
    assert res["summary"]["06 - Concepts/beta.md"]["chunks"] == 1
    assert res["summary"]["06 - Concepts/beta.md"]["est_tokens"] == 4


def test_index_summary_returns_unavailable_when_qdrant_down(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UI must still load when Qdrant is unreachable — empty summary, not a 5xx."""
    _root, documents = tmp_vault

    def _boom():
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(documents, "get_client", _boom)
    res = asyncio.run(documents.index_summary())
    assert res == {"summary": {}, "total_chunks": 0, "available": False}


# ── _iter_notes excludes 04 - Archive ─────────────────────────────────────

def test_iter_notes_skips_archive_folder(tmp_vault):
    root, documents = tmp_vault
    archived = root / "04 - Archive" / "should-be-hidden.md"
    archived.write_text("# hidden\n", encoding="utf-8")

    paths = {str(p.relative_to(root)) for p in documents._iter_notes()}
    assert "04 - Archive/should-be-hidden.md" not in paths
    assert "00 - Inbox/alpha.md" in paths
    assert "06 - Concepts/beta.md" in paths
