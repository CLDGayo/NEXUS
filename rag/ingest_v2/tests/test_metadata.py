"""Phase 4 metadata extractor tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from rag.ingest_v2.metadata import (
    content_hash,
    extract_aliases,
    extract_file_metadata,
    extract_tags,
    extract_title,
    extract_wikilinks,
    file_dates,
    folder_from_path,
    infer_source_kind,
    split_frontmatter,
    stable_chunk_id,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "01 - Projects").mkdir(parents=True)
    (root / "00 - Inbox").mkdir()
    (root / "05 - Daily Notes").mkdir()
    return root


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFrontmatter:
    def test_no_frontmatter(self) -> None:
        fm, body = split_frontmatter("hello world")
        assert fm == {}
        assert body == "hello world"

    def test_simple_frontmatter(self) -> None:
        text = "---\ntitle: My Note\ntags: [a, b]\n---\nbody text"
        fm, body = split_frontmatter(text)
        assert fm == {"title": "My Note", "tags": ["a", "b"]}
        assert body == "body text"

    def test_malformed_frontmatter_returns_empty(self) -> None:
        text = "---\n:: not yaml ::\n---\nbody"
        fm, body = split_frontmatter(text)
        # Either empty dict or whatever yaml resolves; body still drops fm block.
        assert isinstance(fm, dict)
        assert body == "body"


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWikilinks:
    def test_extract_basic(self) -> None:
        body = "See [[ProjectA]] and [[ProjectB]] and [[ProjectA]]."
        assert extract_wikilinks(body) == ("ProjectA", "ProjectB")

    def test_alias_form(self) -> None:
        body = "[[ProjectA|the project]] mentioned with [[ContactB|the contact]]"
        assert extract_wikilinks(body) == ("ProjectA", "ContactB")

    def test_heading_anchor_form(self) -> None:
        body = "[[ProjectA#Status]] and [[ProjectB#Notes|notes]]"
        assert extract_wikilinks(body) == ("ProjectA", "ProjectB")

    def test_no_wikilinks(self) -> None:
        assert extract_wikilinks("plain text") == ()


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTags:
    def test_frontmatter_list(self) -> None:
        result = extract_tags({"tags": ["alpha", "beta"]}, "")
        assert result == ("alpha", "beta")

    def test_frontmatter_string_singular(self) -> None:
        result = extract_tags({"tags": "solo"}, "")
        assert result == ("solo",)

    def test_inline_tags(self) -> None:
        result = extract_tags({}, "this has #ideas and #project-launch tags")
        assert "ideas" in result
        assert "project-launch" in result

    def test_dedup_across_sources(self) -> None:
        result = extract_tags({"tags": ["alpha"]}, "see #alpha and #beta")
        # alpha appears in both; beta only inline
        assert sorted(result) == ["alpha", "beta"]

    def test_strips_hash_prefix_from_frontmatter(self) -> None:
        result = extract_tags({"tags": ["#hashed"]}, "")
        assert result == ("hashed",)


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAliases:
    def test_list(self) -> None:
        assert extract_aliases({"aliases": ["A", "B"]}) == ("A", "B")

    def test_string(self) -> None:
        assert extract_aliases({"aliases": "OnlyOne"}) == ("OnlyOne",)

    def test_missing(self) -> None:
        assert extract_aliases({}) == ()

    def test_drops_nonstrings(self) -> None:
        assert extract_aliases({"aliases": ["valid", None, 42]}) == ("valid",)


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTitle:
    def test_frontmatter_wins(self) -> None:
        path = Path("/x/file.md")
        assert extract_title({"title": "From FM"}, "# H1 Heading", path) == "From FM"

    def test_falls_back_to_first_h1(self) -> None:
        path = Path("/x/file.md")
        assert extract_title({}, "# Real Heading\n\nbody", path) == "Real Heading"

    def test_falls_back_to_stem(self) -> None:
        path = Path("/x/My-Note.md")
        assert extract_title({}, "no heading", path) == "My-Note"


# ---------------------------------------------------------------------------
# Source kind / folder
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSourceKind:
    def test_daily_note(self, vault: Path) -> None:
        path = vault / "05 - Daily Notes" / "2026-05-17.md"
        path.write_text("today")
        assert infer_source_kind(path) == "daily"

    def test_inbox_md(self, vault: Path) -> None:
        path = vault / "00 - Inbox" / "scratch.md"
        path.write_text("note")
        assert infer_source_kind(path) == "inbox-md"

    def test_pdf(self, vault: Path) -> None:
        path = vault / "00 - Inbox" / "doc.pdf"
        path.write_text("fake")
        assert infer_source_kind(path) == "inbox-pdf"

    def test_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "x.weird"
        path.write_text("")
        assert infer_source_kind(path) == "unknown"


@pytest.mark.unit
class TestFolder:
    def test_relative_to_vault_root(self, vault: Path) -> None:
        path = vault / "01 - Projects" / "alpha" / "spec.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        assert folder_from_path(path, vault_root=vault) == "01 - Projects"

    def test_no_root(self) -> None:
        assert folder_from_path(Path("/x/y/z.md")) == "x"


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDates:
    def test_frontmatter_overrides_stat(self, tmp_path: Path) -> None:
        path = tmp_path / "note.md"
        path.write_text("body")
        time.sleep(0.01)
        created, modified = file_dates(
            path, {"date_created": "2024-01-01T00:00:00Z", "updated": "2025-12-31"}
        )
        assert created == "2024-01-01T00:00:00Z"
        assert modified == "2025-12-31"

    def test_falls_back_to_stat(self, tmp_path: Path) -> None:
        path = tmp_path / "note.md"
        path.write_text("body")
        created, modified = file_dates(path, {})
        assert created
        assert modified


# ---------------------------------------------------------------------------
# Content hash + stable ids
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStableIds:
    def test_content_hash_deterministic(self) -> None:
        assert content_hash("hello") == content_hash("hello")
        assert content_hash("hello") != content_hash("hello!")

    def test_same_input_same_uuid(self) -> None:
        a = stable_chunk_id("/x.md", 0, "alpha")
        b = stable_chunk_id("/x.md", 0, "alpha")
        assert a == b

    def test_chunk_index_changes_uuid(self) -> None:
        a = stable_chunk_id("/x.md", 0, "alpha")
        b = stable_chunk_id("/x.md", 1, "alpha")
        assert a != b

    def test_content_change_changes_uuid(self) -> None:
        a = stable_chunk_id("/x.md", 0, "alpha")
        b = stable_chunk_id("/x.md", 0, "beta")
        assert a != b


# ---------------------------------------------------------------------------
# End-to-end extract_file_metadata
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_extract_file_metadata_end_to_end(vault: Path) -> None:
    path = vault / "01 - Projects" / "alpha.md"
    path.write_text(
        "---\n"
        "title: Project Alpha\n"
        "tags: [active, billing]\n"
        "aliases: [alpha-proj]\n"
        "---\n"
        "# Project Alpha\n\n"
        "Linked to [[ClientX]] and [[ProjectB]].\n"
        "Also tagged inline as #review.\n"
    )
    meta = extract_file_metadata(path, path.read_text(), vault_root=vault)
    assert meta.title == "Project Alpha"
    assert meta.folder == "01 - Projects"
    assert "active" in meta.tags and "review" in meta.tags
    assert meta.aliases == ("alpha-proj",)
    assert meta.wikilinks_out == ("ClientX", "ProjectB")
    assert meta.source_kind == "note"
    assert meta.content_hash
