"""Documents listing — walk vault, parse frontmatter, paginate.

Also exposes synchronized soft-delete (move to 04 - Archive/ + purge vectors)
and vault reconciliation (drop Qdrant points whose source file no longer
exists in the active vault).
"""

import logging
import os
import shutil
from pathlib import Path

import frontmatter
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ingest import COLLECTION, get_client
from inbox import delete_vectors_for_file
from routers.deps import require_auth

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"], dependencies=[Depends(require_auth)])

VAULT_PATH = os.environ.get("VAULT_PATH", "")
ARCHIVE_FOLDER = "04 - Archive"
_SKIP = {".obsidian", "_publish", "rag", ".git", "node_modules", "templates", ARCHIVE_FOLDER}


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


# ── Soft-delete (archive) ──────────────────────────────────────────────────

class ArchiveRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=500)


def _resolve_inside_vault(rel_path: str, root: Path) -> Path:
    """Return the absolute path for ``rel_path`` if it is safely inside the vault.

    Raises HTTPException(400) on traversal attempts, absolute paths, or anything
    that escapes the vault root after resolution.
    """
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise HTTPException(status_code=400, detail=f"Invalid path: {rel_path!r}")
    candidate = (root / rel_path).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Path escapes vault: {rel_path!r}"
        ) from exc
    return candidate


def _unique_path(target: Path) -> Path:
    """Return a path that does not yet exist, suffixing with ' (2)', ' (3)', ..."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 2
    while True:
        candidate = target.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _archive_one(rel_path: str, root: Path) -> tuple[str, str]:
    """Move ``rel_path`` into ``04 - Archive/`` preserving its source folder.

    Returns ``(new_rel_path, original_rel_path_for_vector_purge)``. Raises
    HTTPException for caller-visible failures.
    """
    src = _resolve_inside_vault(rel_path, root)
    rel = src.relative_to(root.resolve())
    rel_str = str(rel)

    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {rel_path}")
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {rel_path}")
    if rel.parts and rel.parts[0] == ARCHIVE_FOLDER:
        # Idempotent: already archived. Still purge vectors in case any leaked.
        return rel_str, rel_str

    dst = _unique_path(root / ARCHIVE_FOLDER / rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    new_rel = str(dst.relative_to(root.resolve()))
    return new_rel, rel_str


@router.post("/documents/archive")
async def archive_documents(req: ArchiveRequest) -> dict:
    """Soft-delete: move each note into ``04 - Archive/`` and purge its vectors.

    Per-path errors are collected into ``failed`` rather than aborting the batch.
    """
    root = _vault_root()
    archived: list[dict] = []
    failed: list[dict] = []
    purged = 0

    for rel_path in req.paths:
        try:
            new_rel, orig_rel = _archive_one(rel_path, root)
        except HTTPException as exc:
            failed.append({"path": rel_path, "error": exc.detail})
            continue
        except Exception as exc:  # noqa: BLE001 — surface to caller, keep batch alive
            log.exception("archive failed for %s", rel_path)
            failed.append({"path": rel_path, "error": str(exc)})
            continue

        # Best-effort vector purge — the helper already swallows + logs.
        try:
            delete_vectors_for_file(orig_rel)
            purged += 1
        except Exception as exc:  # noqa: BLE001 — defensive; helper itself catches
            log.warning("vector purge failed for %s: %s", orig_rel, exc)

        archived.append({"path": rel_path, "archived_path": new_rel})

    return {"archived": archived, "failed": failed, "vectors_purged": purged}


# ── Vault reconciliation (orphan cleanup) ──────────────────────────────────

def _qdrant_indexed_files() -> set[str]:
    """Scroll the collection and collect every unique ``payload.file`` value."""
    client = get_client()
    files: set[str] = set()
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=512,
            with_payload=["file"],
            with_vectors=False,
            offset=next_offset,
        )
        for p in points:
            payload = p.payload or {}
            f = payload.get("file")
            if isinstance(f, str) and f:
                files.add(f)
        if next_offset is None:
            break
    return files


def _qdrant_index_summary() -> dict[str, dict[str, int]]:
    """Return ``{rel_path: {"chunks": N, "est_tokens": M}}`` from a single scroll.

    ``est_tokens`` sums ``len(text)//4`` over each chunk's payload — matches the
    naive token estimate used by the chunker (``ingest.naive_token_count``).
    """
    client = get_client()
    summary: dict[str, dict[str, int]] = {}
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=512,
            with_payload=["file", "text"],
            with_vectors=False,
            offset=next_offset,
        )
        for p in points:
            payload = p.payload or {}
            f = payload.get("file")
            if not isinstance(f, str) or not f:
                continue
            text = payload.get("text") or ""
            entry = summary.setdefault(f, {"chunks": 0, "est_tokens": 0})
            entry["chunks"] += 1
            entry["est_tokens"] += max(1, len(text) // 4)
        if next_offset is None:
            break
    return summary


@router.get("/documents/index_summary")
async def index_summary() -> dict:
    """Per-file chunk count + token estimate from the live Qdrant collection.

    Returns ``{"summary": {<rel_path>: {chunks, est_tokens}}, "total_chunks": N}``.
    Best-effort — if Qdrant is unreachable the summary is empty rather than 502,
    so the Documents page can still render the file listing.
    """
    try:
        summary = _qdrant_index_summary()
    except Exception as exc:  # noqa: BLE001 — UI should still load if Qdrant is down
        log.warning("index_summary scroll failed: %s", exc)
        return {"summary": {}, "total_chunks": 0, "available": False}

    total_chunks = sum(v["chunks"] for v in summary.values())
    return {"summary": summary, "total_chunks": total_chunks, "available": True}


@router.post("/documents/reconcile")
async def reconcile_vault() -> dict:
    """Find Qdrant points whose source file no longer exists in the active vault.

    "Active vault" means everything ``_iter_notes`` would list — i.e. excluding
    ``04 - Archive/`` and the other ``_SKIP`` folders.
    """
    root = _vault_root()

    try:
        qdrant_files = _qdrant_indexed_files()
    except Exception as exc:
        log.exception("qdrant scroll failed during reconcile")
        raise HTTPException(status_code=502, detail=f"Qdrant unreachable: {exc}") from exc

    active_files = {str(p.relative_to(root)) for p in _iter_notes()}

    orphans = sorted(qdrant_files - active_files)
    purged = 0
    for orphan in orphans:
        try:
            delete_vectors_for_file(orphan)
            purged += 1
        except Exception as exc:  # noqa: BLE001 — keep going on individual failures
            log.warning("vector purge failed for orphan %s: %s", orphan, exc)

    return {
        "qdrant_files": len(qdrant_files),
        "active_files": len(active_files),
        "orphans": orphans,
        "purged": purged,
    }
