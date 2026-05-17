"""Metadata extraction for ingest chunks.

Per CLAUDE.md §1 Stage 2 every chunk carries: file, folder, title,
heading_path, tags, aliases, wikilinks_out, date_created, date_modified,
content_hash, chunk_index, chunk_total, source_kind. We extract everything
we can at ingest time so the query path never has to re-parse a file.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Match `[[Target]]`, `[[Target|alias]]`, and `[[Target#heading]]`.
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]")
# Same target shape, but with explicit groups for the anchor and the alias.
# Phase 7 graph builder uses this to persist link anchors + aliases.
_WIKILINK_DETAIL_RE = re.compile(
    r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]+))?\]\]"
)
# Inline tags `#tag-name` not inside code spans.
_INLINE_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z][\w/-]*)")
# Frontmatter delimiter (Obsidian/Jekyll style: --- at line start).
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


# Deterministic namespace for IngestChunk ids — never change after first
# deploy, otherwise re-ingest creates duplicate Qdrant points.
_NEXUS_NAMESPACE = uuid.UUID("8a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d")


@dataclass(frozen=True)
class FileMetadata:
    """Extracted once per file. Combined with per-chunk fields downstream."""

    file: str
    folder: str
    title: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    wikilinks_out: tuple[str, ...]
    date_created: str
    date_modified: str
    content_hash: str
    source_kind: str
    frontmatter: dict[str, Any] = field(default_factory=dict)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter_dict, body)``. Empty dict if none."""

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    yaml_text = match.group(1)
    body = text[match.end():]

    try:
        import yaml as _yaml  # local import — yaml is a small dep
    except ImportError:
        return {}, body

    try:
        data = _yaml.safe_load(yaml_text) or {}
        if not isinstance(data, dict):
            return {}, body
        return data, body
    except Exception:
        return {}, body


def extract_wikilinks(body: str) -> tuple[str, ...]:
    """Unique, order-preserving outbound wikilink targets."""

    seen: dict[str, None] = {}
    for match in _WIKILINK_RE.finditer(body):
        target = match.group(1).strip()
        if target:
            seen.setdefault(target, None)
    return tuple(seen)


def extract_wikilinks_detailed(
    body: str,
) -> tuple[tuple[str, str | None, str | None], ...]:
    """Order-preserving ``(target, anchor, alias)`` triples.

    Unlike :func:`extract_wikilinks`, duplicates (same target but different
    anchor/alias) are preserved so the graph builder can store every edge.
    """

    out: list[tuple[str, str | None, str | None]] = []
    for match in _WIKILINK_DETAIL_RE.finditer(body):
        target = match.group(1).strip()
        if not target:
            continue
        anchor = (match.group(2) or "").strip() or None
        alias = (match.group(3) or "").strip() or None
        out.append((target, anchor, alias))
    return tuple(out)


def extract_tags(frontmatter: dict[str, Any], body: str) -> tuple[str, ...]:
    """Merge frontmatter ``tags:`` with inline ``#tag`` occurrences."""

    seen: dict[str, None] = {}

    fm_tags = frontmatter.get("tags") if frontmatter else None
    if isinstance(fm_tags, str):
        fm_tags = [fm_tags]
    if isinstance(fm_tags, list):
        for tag in fm_tags:
            if isinstance(tag, str) and tag.strip():
                seen.setdefault(tag.strip().lstrip("#").lower(), None)

    for match in _INLINE_TAG_RE.finditer(body):
        seen.setdefault(match.group(1).lower(), None)

    return tuple(seen)


def extract_aliases(frontmatter: dict[str, Any]) -> tuple[str, ...]:
    raw = frontmatter.get("aliases") if frontmatter else None
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(item for item in raw if isinstance(item, str) and item)
    return ()


def extract_title(frontmatter: dict[str, Any], body: str, path: Path) -> str:
    fm_title = (frontmatter or {}).get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()

    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or path.stem
    return path.stem


def infer_source_kind(path: Path, vault_root: Path | None = None) -> str:
    """Heuristic mapping vault structure → ``source_kind`` payload field."""

    suffix = path.suffix.lower()
    parts = path.parts
    in_inbox = any("Inbox" in part for part in parts)

    if suffix == ".pdf":
        return "inbox-pdf" if in_inbox else "pdf"
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return f"office-{suffix.lstrip('.')}"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff"}:
        return "image"
    if suffix in {".md", ".markdown"}:
        if any(p.startswith("05") and "Daily" in p for p in parts):
            return "daily"
        if in_inbox:
            return "inbox-md"
        return "note"
    return "unknown"


def file_dates(path: Path, frontmatter: dict[str, Any]) -> tuple[str, str]:
    """Return ``(date_created, date_modified)`` as ISO-8601 UTC strings.

    Frontmatter takes precedence over filesystem stat so the vault owner's
    explicit dates survive file moves/touches.
    """

    fm = frontmatter or {}
    fm_created = fm.get("date_created") or fm.get("created")
    fm_modified = fm.get("date_modified") or fm.get("modified") or fm.get("updated")

    def _to_iso(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    stat = path.stat()
    created = _to_iso(fm_created) or datetime.fromtimestamp(
        stat.st_ctime, tz=timezone.utc
    ).isoformat()
    modified = _to_iso(fm_modified) or datetime.fromtimestamp(
        stat.st_mtime, tz=timezone.utc
    ).isoformat()
    return created, modified


def folder_from_path(path: Path, vault_root: Path | None = None) -> str:
    """Top-level vault folder (the PARA bucket) or the first real ancestor.

    With ``vault_root`` set, returns the directory directly under the vault.
    Without a vault root, returns the first path component that is not the
    filesystem root marker (e.g. ``/`` on POSIX).
    """

    if vault_root is not None:
        try:
            relative = path.relative_to(vault_root)
        except ValueError:
            relative = path
    else:
        relative = path

    for part in relative.parts[:-1]:
        if part in ("/", "\\", ""):
            continue
        return part
    return ""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_chunk_id(file_path: str, chunk_index: int, chunk_text: str) -> str:
    """Deterministic UUIDv5 for a chunk. Re-ingest is idempotent."""

    key = f"{file_path}::{chunk_index}::{content_hash(chunk_text)}"
    return str(uuid.uuid5(_NEXUS_NAMESPACE, key))


def extract_file_metadata(
    path: Path,
    text: str,
    *,
    vault_root: Path | None = None,
) -> FileMetadata:
    """End-to-end metadata extraction for one source file.

    ``text`` should be the post-multimodal Markdown body (frontmatter parsed
    separately inside this function). ``vault_root`` lets us derive a PARA
    folder; pass ``None`` for ad-hoc files.
    """

    frontmatter, body = split_frontmatter(text)
    return FileMetadata(
        file=str(path),
        folder=folder_from_path(path, vault_root=vault_root),
        title=extract_title(frontmatter, body, path),
        tags=extract_tags(frontmatter, body),
        aliases=extract_aliases(frontmatter),
        wikilinks_out=extract_wikilinks(body),
        date_created=file_dates(path, frontmatter)[0],
        date_modified=file_dates(path, frontmatter)[1],
        content_hash=content_hash(body),
        source_kind=infer_source_kind(path, vault_root=vault_root),
        frontmatter=dict(frontmatter),
    )
