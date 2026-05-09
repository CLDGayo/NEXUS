"""Documents listing — walk vault, parse frontmatter, paginate."""

import os
from pathlib import Path

import frontmatter
from fastapi import APIRouter, Depends, Query

from routers.deps import require_auth

router = APIRouter(tags=["documents"], dependencies=[Depends(require_auth)])

VAULT_PATH = os.environ.get("VAULT_PATH", "")
_SKIP = {".obsidian", "_publish", "rag", ".git", "node_modules", "templates"}


def _vault_root() -> Path:
    return Path(VAULT_PATH) if VAULT_PATH else Path(__file__).parent.parent.parent


def _iter_notes():
    root = _vault_root()
    for p in sorted(root.rglob("*.md")):
        if any(skip in p.parts for skip in _SKIP):
            continue
        yield p


def _parse_note(path: Path, root: Path) -> dict:
    try:
        post = frontmatter.load(str(path))
        title = post.get("title") or path.stem
        tags = post.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
    except Exception:
        title = path.stem
        tags = []

    rel = path.relative_to(root)
    folder = rel.parts[0] if len(rel.parts) > 1 else "/"

    return {
        "path": str(rel),
        "title": title,
        "folder": folder,
        "tags": tags[:6],
        "modified": path.stat().st_mtime,
    }


@router.get("/documents")
async def list_documents(
    search: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    root = _vault_root()
    items = [_parse_note(p, root) for p in _iter_notes()]

    if search:
        q = search.lower()
        items = [
            d for d in items
            if q in d["title"].lower()
            or q in d["folder"].lower()
            or any(q in t.lower() for t in d["tags"])
        ]

    total = len(items)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    return {"items": items[start : start + limit], "total": total, "pages": pages}
