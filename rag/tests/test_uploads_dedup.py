"""Unit tests for content-hash dedup, vector GC, and frontmatter injection.

Run from the rag/ directory:
    uv run --with pytest pytest tests/test_uploads_dedup.py -v
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import frontmatter
import pytest


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point VAULT_PATH at a temp dir and re-import inbox so INBOX picks it up."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    inbox_dir = tmp_path / "00 - Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Force a re-import so module-level constants pick up the new env var.
    import importlib

    import inbox as _inbox

    importlib.reload(_inbox)
    return tmp_path


def test_compute_content_hash_text_is_stable(tmp_vault: Path) -> None:
    from inbox import compute_content_hash

    text = "hello world"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert compute_content_hash(text) == expected
    assert compute_content_hash(text) == compute_content_hash(text)


def test_compute_content_hash_pdf_bytes(tmp_vault: Path) -> None:
    from inbox import compute_content_hash

    # PDF binary often contains non-UTF-8 bytes; the bytes path must hash them as-is.
    raw = b"%PDF-1.4\n\x80\x81\x82\xfffake-pdf-bytes\n"
    expected = hashlib.sha256(raw).hexdigest()
    assert compute_content_hash(raw) == expected
    assert compute_content_hash(raw) == compute_content_hash(raw)


def test_write_note_at_injects_hash_and_metadata(tmp_vault: Path) -> None:
    from inbox import write_note_at

    target = tmp_vault / "00 - Inbox" / "alpha.md"
    h = "deadbeef" * 8
    write_note_at(
        target,
        title="alpha",
        content="body content",
        source_filename="alpha.md",
        tags=["inbox", "upload"],
        content_hash=h,
    )

    assert target.exists()
    post = frontmatter.load(str(target))
    assert post.metadata["content_hash"] == h
    assert post.metadata["date_ingested"]
    assert post.metadata["title"] == "alpha"
    assert post.metadata["source"] == "alpha.md"
    assert post.metadata["tags"] == ["inbox", "upload"]
    assert "body content" in post.content


def test_write_note_at_preserves_existing_yaml(tmp_vault: Path) -> None:
    from inbox import write_note_at

    target = tmp_vault / "00 - Inbox" / "preserve.md"
    md_with_yaml = (
        "---\n"
        "title: User Title\n"
        "aliases:\n"
        "  - User Alias\n"
        "custom_key: keep-me\n"
        "---\n"
        "\nactual body\n"
    )
    write_note_at(
        target,
        title="fallback",
        content=md_with_yaml,
        source_filename="preserve.md",
        tags=["inbox", "upload"],
        content_hash="abc123",
        preserve_existing_yaml=True,
    )

    post = frontmatter.load(str(target))
    assert post.metadata["title"] == "User Title"  # user's value preserved
    assert post.metadata["custom_key"] == "keep-me"
    assert post.metadata["aliases"] == ["User Alias"]
    assert post.metadata["content_hash"] == "abc123"  # always set
    assert "actual body" in post.content


def test_write_note_at_overwrites_when_preserve_false(tmp_vault: Path) -> None:
    """preserve_existing_yaml=False: input content is treated as raw body."""
    from inbox import write_note_at

    target = tmp_vault / "00 - Inbox" / "raw.md"
    write_note_at(
        target,
        title="raw",
        content="---\ntitle: ignored\n---\njust body",  # raw, not parsed
        source_filename="raw.md",
        tags=["inbox", "upload"],
        content_hash="hh",
        preserve_existing_yaml=False,
    )
    post = frontmatter.load(str(target))
    assert post.metadata["title"] == "raw"  # our default, not "ignored"


def test_delete_vectors_for_file_swallows_errors(
    tmp_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If Qdrant is unreachable, GC must not raise."""
    import inbox

    def _boom() -> None:
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(inbox, "get_client", _boom)
    # Should NOT raise
    inbox.delete_vectors_for_file("00 - Inbox/missing.md")


def test_delete_vectors_for_file_calls_qdrant_with_filter(
    tmp_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the delete payload targets the `file` payload key."""
    import inbox

    captured: dict = {}

    class StubClient:
        def delete(self, *, collection_name: str, points_selector, wait: bool) -> None:  # noqa: ANN001
            captured["collection_name"] = collection_name
            captured["points_selector"] = points_selector
            captured["wait"] = wait

    monkeypatch.setattr(inbox, "get_client", lambda: StubClient())
    inbox.delete_vectors_for_file("00 - Inbox/example.md")

    assert captured["collection_name"] == os.environ.get(
        "QDRANT_COLLECTION", "nexus-vault"
    )
    assert captured["wait"] is True
    selector = captured["points_selector"]
    # The filter must reference the `file` payload key with our rel_path value.
    selector_repr = repr(selector)
    assert "file" in selector_repr
    assert "00 - Inbox/example.md" in selector_repr
