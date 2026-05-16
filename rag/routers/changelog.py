"""Changelog router — parses CHANGELOG.md and tracks unread state.

The parser is intentionally tiny: split on lines starting with `## [`, treat
the first line of each block as `[version] - YYYY-MM-DD`, and detect type
tags from `### Added|Changed|Fixed|Removed|Security` subsections.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends

import settings_service
from database import now_iso
from routers.deps import require_auth

router = APIRouter(tags=["changelog"], dependencies=[Depends(require_auth)])


def _resolve_changelog_path() -> Path:
    """Locate CHANGELOG.md across Mac dev layout and VPS prod layout."""
    override = os.getenv("CHANGELOG_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "CHANGELOG.md",       # Mac dev: vault root
        here.parents[1] / "CHANGELOG.md",       # rag/CHANGELOG.md
        Path("/home/nexus-vault/CHANGELOG.md"),  # VPS prod: vault path
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


_CHANGELOG_PATH = _resolve_changelog_path()

_HEADER_RE = re.compile(r"^##\s+\[(?P<version>[^\]]+)\]\s*-\s*(?P<date>\S+)\s*$")
_SUBHEAD_RE = re.compile(r"^###\s+(?P<tag>\w+)\s*$")


def _parse(text: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        if current is None:
            return
        current["body_md"] = "\n".join(body_lines).strip()
        entries.append(current)

    for line in text.splitlines():
        header = _HEADER_RE.match(line)
        if header:
            _flush()
            current = {
                "version": header["version"],
                "date": header["date"],
                "type_tags": [],
                "body_md": "",
            }
            body_lines = []
            continue
        if current is None:
            continue
        body_lines.append(line)
        sub = _SUBHEAD_RE.match(line)
        if sub:
            tag = sub["tag"].lower()
            if tag not in current["type_tags"]:
                current["type_tags"].append(tag)

    _flush()
    return entries


def _load_entries() -> list[dict]:
    if not _CHANGELOG_PATH.exists():
        return []
    return _parse(_CHANGELOG_PATH.read_text(encoding="utf-8"))


@router.get("")
async def list_changelog() -> dict:
    entries = _load_entries()
    return {"entries": entries, "count": len(entries)}


@router.get("/unread")
async def changelog_unread() -> dict:
    entries = _load_entries()
    last_read = await settings_service.get("changelog_last_read") or ""
    unread = [e for e in entries if e["date"] > last_read]
    latest = entries[0]["version"] if entries else None
    return {"unread_count": len(unread), "latest_version": latest}


@router.post("/mark-read")
async def mark_read() -> dict:
    ts = now_iso()
    await settings_service.set_value("changelog_last_read", ts)
    return {"ok": True, "marked_at": ts}
