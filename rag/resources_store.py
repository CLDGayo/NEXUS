"""Prompt + template library backed by `<VAULT>/03 - Resources/prompts/`.

Each prompt is a markdown file with YAML frontmatter:

    ---
    name: "Concise Analyst"
    category: "system-prompt"
    tags: [analyst, terse]
    model: "llama-3.3-70b-versatile"
    ---
    You are NEXUS, a terse analyst. Cite sources. Refuse when uncovered.

The body (text after frontmatter) is the prompt content.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import frontmatter

import settings_service

_RESOURCES_SUBDIR = "03 - Resources/prompts"


def _vault_root() -> Path:
    p = os.environ.get("VAULT_PATH", "")
    if not p:
        return Path(__file__).parent.parent
    return Path(p)


def prompts_dir() -> Path:
    return _vault_root() / _RESOURCES_SUBDIR


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "prompt"


def _path_for(slug: str) -> Path:
    return prompts_dir() / f"{slug}.md"


def list_prompts() -> list[dict[str, Any]]:
    folder = prompts_dir()
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(folder.glob("*.md")):
        try:
            post = frontmatter.load(str(p))
        except Exception:  # noqa: BLE001
            continue
        meta = dict(post.metadata)
        body = post.content.strip()
        out.append(
            {
                "slug": p.stem,
                "name": meta.get("name", p.stem),
                "category": meta.get("category", "system-prompt"),
                "tags": meta.get("tags", []),
                "model": meta.get("model", ""),
                "preview": body[:200],
            }
        )
    return out


def read_prompt(slug: str) -> dict[str, Any] | None:
    p = _path_for(slug)
    if not p.exists():
        return None
    post = frontmatter.load(str(p))
    meta = dict(post.metadata)
    return {
        "slug": slug,
        "name": meta.get("name", slug),
        "category": meta.get("category", "system-prompt"),
        "tags": meta.get("tags", []),
        "model": meta.get("model", ""),
        "body": post.content.strip(),
    }


def write_prompt(slug: str, name: str, body: str, metadata: dict[str, Any] | None = None) -> Path:
    folder = prompts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body)
    post.metadata.update(
        {"name": name, "category": "system-prompt", **(metadata or {})}
    )
    target = _path_for(slug)
    target.write_text(frontmatter.dumps(post), encoding="utf-8")
    return target


def delete_prompt(slug: str) -> bool:
    p = _path_for(slug)
    if not p.exists():
        return False
    archive_root = _vault_root() / "04 - Archive" / _RESOURCES_SUBDIR
    archive_root.mkdir(parents=True, exist_ok=True)
    p.rename(archive_root / p.name)
    return True


_DEFAULT_SEEDS = [
    (
        "concise-analyst",
        "Concise Analyst",
        "You are NEXUS, a terse analyst. Answer in <=4 sentences. "
        "Cite numbered sources [n] for every factual claim. "
        "Refuse when the vault context cannot support the answer.",
    ),
    (
        "research-deep",
        "Deep Researcher",
        "You are NEXUS in deep research mode. Decompose the question, "
        "synthesize across multiple sources, note contradictions explicitly, "
        "and end with a 'Open questions' section. Always cite [n].",
    ),
    (
        "writing-coach",
        "Writing Coach",
        "You are NEXUS as a writing coach. Critique structure, voice, and clarity. "
        "Cite the user's prior notes [n] when proposing changes.",
    ),
]


def seed_defaults() -> list[str]:
    """Idempotent: writes default prompts only when the folder is empty."""
    folder = prompts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.glob("*.md")):
        return []
    written: list[str] = []
    for slug, name, body in _DEFAULT_SEEDS:
        write_prompt(slug, name, body)
        written.append(slug)
    return written


async def load_active_system_prompt() -> str | None:
    """Return the active resource prompt body, or None to fall back to baked-in."""
    slug = await settings_service.get("system_prompt_id")
    if not slug:
        return None
    p = read_prompt(str(slug))
    if not p:
        return None
    return p["body"] or None
