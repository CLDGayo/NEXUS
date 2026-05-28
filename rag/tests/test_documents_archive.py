"""Unit tests for the synchronized soft-delete + vault reconciliation endpoints.

Run from the rag/ directory:
    uv run --with pytest pytest tests/test_documents_archive.py -v
"""

from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        self.email = "tester@nexus.test"


class _FakeTenant:
    def __init__(self, slug: str = "hunter") -> None:
        self.id = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
        self.name = "Hunter"
        self.slug = slug
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


_USER = _FakeUser()
_TENANT = _FakeTenant()


class _StubSession:
    """Async-session shim sufficient for the documents router's archive +
    reconcile codepaths.

    Phase 31 — archive_documents calls ``select(Document)`` per path then
    flips ``archived_at`` on the returned row (or no-ops if absent).
    reconcile_vault calls ``select(Document.file)`` to enumerate live
    docs. The stub returns a configurable set of paths so tests can pin
    the active_files count without standing up Postgres.
    """

    def __init__(self, live_files: tuple[str, ...] = ()) -> None:
        self._live_files = tuple(live_files)
        self.committed = False

    async def execute(self, stmt):  # noqa: ANN001 — duck-typed for tests
        return _StubResult(self._live_files)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:  # pragma: no cover — defensive
        pass


class _StubResult:
    def __init__(self, live_files: tuple[str, ...]) -> None:
        self._live_files = live_files

    def scalar_one_or_none(self):
        # archive_documents looks up a single Document per path; we
        # always return None (no row) so the `if doc is not None` branch
        # is skipped. The vector-purge + filesystem-move assertions
        # still hold because they don't depend on the DB row.
        return None

    def all(self):
        return [(f,) for f in self._live_files]


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
    purged_paths: list[tuple[str, str]] = []
    monkeypatch.setattr(
        documents,
        "delete_vectors_for_file",
        lambda rel, *, tenant_slug: purged_paths.append((rel, tenant_slug)),
    )

    req = documents.ArchiveRequest(paths=[
        "00 - Inbox/alpha.md",
        "06 - Concepts/beta.md",
    ])
    res = asyncio.run(
        documents.archive_documents(
            req, user=_USER, tenant=_TENANT, db=_StubSession()
        )
    )

    assert len(res["archived"]) == 2
    assert res["failed"] == []
    assert res["vectors_purged"] == 2
    # Vector purge uses the ORIGINAL rel_path (matches Qdrant payload.file)
    # plus the active tenant slug (Phase 29 — prevents cross-tenant purge).
    assert sorted(purged_paths) == [
        ("00 - Inbox/alpha.md", "hunter"),
        ("06 - Concepts/beta.md", "hunter"),
    ]
    assert (root / "04 - Archive" / "00 - Inbox" / "alpha.md").exists()
    assert (root / "04 - Archive" / "06 - Concepts" / "beta.md").exists()


def test_archive_documents_collects_per_item_failures(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault
    monkeypatch.setattr(
        documents,
        "delete_vectors_for_file",
        lambda _rel, *, tenant_slug: None,
    )

    req = documents.ArchiveRequest(paths=[
        "00 - Inbox/alpha.md",
        "00 - Inbox/missing.md",       # 404
        "../escape.md",                  # 400
    ])
    res = asyncio.run(
        documents.archive_documents(
            req, user=_USER, tenant=_TENANT, db=_StubSession()
        )
    )

    assert len(res["archived"]) == 1
    assert len(res["failed"]) == 2
    failed_paths = {f["path"] for f in res["failed"]}
    assert failed_paths == {"00 - Inbox/missing.md", "../escape.md"}


# ── reconcile_vault endpoint ──────────────────────────────────────────────

class _StubScrollClient:
    """Stand-in for QdrantClient.scroll — yields one page then signals done.

    Accepts either ``list[str]`` (just file names) or ``list[dict]`` payloads
    so tests can also exercise the index-summary path that needs ``text``.
    Phase 29 — accepts ``scroll_filter`` and records it so tests can assert
    the tenant predicate was supplied.
    """
    def __init__(self, items) -> None:  # noqa: ANN001
        self._items = items
        self.last_filter = None

    def scroll(self, *, collection_name, limit, with_payload, with_vectors, offset, scroll_filter=None):  # noqa: ANN001
        self.last_filter = scroll_filter
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
    stub_client = _StubScrollClient(qdrant_files)
    monkeypatch.setattr(documents, "get_client", lambda: stub_client)
    purged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        documents,
        "delete_vectors_for_file",
        lambda rel, *, tenant_slug: purged.append((rel, tenant_slug)),
    )

    live = _StubSession(
        live_files=("00 - Inbox/alpha.md", "06 - Concepts/beta.md")
    )
    res = asyncio.run(
        documents.reconcile_vault(user=_USER, tenant=_TENANT, db=live)
    )

    assert res["qdrant_files"] == 3
    assert res["active_files"] == 2
    assert res["orphans"] == ["06 - Concepts/ghost.md"]
    assert res["purged"] == 1
    assert purged == [("06 - Concepts/ghost.md", "hunter")]
    # Phase 29 — every scroll must carry the tenant filter.
    assert stub_client.last_filter is not None


def test_reconcile_no_orphans_when_in_sync(
    tmp_vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, documents = tmp_vault
    monkeypatch.setattr(
        documents,
        "get_client",
        lambda: _StubScrollClient(["00 - Inbox/alpha.md", "06 - Concepts/beta.md"]),
    )
    purged: list[tuple[str, str]] = []
    monkeypatch.setattr(
        documents,
        "delete_vectors_for_file",
        lambda rel, *, tenant_slug: purged.append((rel, tenant_slug)),
    )

    live = _StubSession(
        live_files=("00 - Inbox/alpha.md", "06 - Concepts/beta.md")
    )
    res = asyncio.run(
        documents.reconcile_vault(user=_USER, tenant=_TENANT, db=live)
    )
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
        asyncio.run(
            documents.reconcile_vault(
                user=_USER, tenant=_TENANT, db=_StubSession()
            )
        )
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

    res = asyncio.run(documents.index_summary(user=_USER, tenant=_TENANT))

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
    res = asyncio.run(documents.index_summary(user=_USER, tenant=_TENANT))
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
