"""Documents listing — Postgres-backed registry + Qdrant reconciliation.

Phase 31 closes the horizontal data leak that the original filesystem
walker introduced. ``GET /api/documents`` now reads ``app.documents``
filtered by ``tenant_id``; the on-disk vault is still shared (per the
Architect's clarification) but the registry rows are not. Two tenants
ingesting the same file path see disjoint result sets keyed on their
respective Document rows.

The legacy ``_SKIP`` set picks up ``.venv`` and ``__pycache__`` as
defence-in-depth — even if a future helper falls back to walking the
filesystem, it cannot leak Python source files into the Documents tab.

Archive / reconcile semantics:
    * ``POST /documents/archive`` flips ``Document.archived_at = now()``
      and continues to move the file into ``04 - Archive/`` and purge
      its Qdrant chunks (tenant-scoped).
    * ``POST /documents/reconcile`` walks Qdrant for the active tenant
      and the active ``app.documents`` (non-archived) — orphans are
      Qdrant points whose file no longer has a live Document row.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ingest import COLLECTION, get_client
from inbox import delete_vectors_for_file

from rag.auth import current_active_user, get_current_tenant
from rag.database.engine import get_async_session
from rag.database.models import Document, Product, Tenant, User

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

VAULT_PATH = os.environ.get("VAULT_PATH", "")
ARCHIVE_FOLDER = "04 - Archive"

# Phase 31 — `.venv`, `__pycache__`, and source-tree directories are
# explicitly excluded so the legacy filesystem helpers (archive resolve,
# reconcile orphan diff) never surface non-vault artifacts.
_SKIP = {
    ".obsidian",
    "_publish",
    "rag",
    ".git",
    "node_modules",
    "templates",
    ".venv",
    "__pycache__",
    ARCHIVE_FOLDER,
}


def _vault_root() -> Path:
    return Path(VAULT_PATH) if VAULT_PATH else Path(__file__).parent.parent.parent


def _iter_notes():
    """Defensive filesystem walker retained from the pre-Phase-31 design.

    Not consulted by the live ``/api/documents`` endpoint (that now reads
    from ``app.documents``). Kept available so a future ad-hoc tool —
    e.g. a one-shot vault audit — does not silently leak ``.venv`` or
    ``__pycache__`` artifacts. ``_SKIP`` includes both defensively.
    """

    root = _vault_root()
    for p in sorted(root.rglob("*.md")):
        if any(skip in p.parts for skip in _SKIP):
            continue
        yield p


def _tenant_filter(tenant_slug: str) -> Filter:
    return Filter(
        must=[
            FieldCondition(
                key="tenant_id", match=MatchValue(value=tenant_slug)
            )
        ]
    )


def _document_to_dict(doc: Document) -> dict:
    return {
        "path": doc.file,
        "title": doc.title or Path(doc.file).stem,
        "folder": doc.folder or "/",
        "tags": list(doc.tags or [])[:6],
        "modified": (
            doc.modified_at.timestamp()
            if doc.modified_at is not None
            else doc.indexed_at.timestamp()
        ),
        "source_kind": doc.source_kind or "note",
    }


def _product_to_doc_dict(product: Product) -> dict:
    """Phase 32.2 — surface products in the Documents list under a synthetic
    ``/products`` folder. Same row shape as a Document so the SPA renders
    them without any frontend change."""
    return {
        "path": f"/products/{product.slug}",
        "title": product.name,
        "folder": "/products",
        "tags": ["product"],
        "modified": product.updated_at.timestamp(),
        "source_kind": "product",
    }


@router.get("/documents")
async def list_documents(
    search: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """List documents for the active tenant from ``app.documents``.

    Reads the per-tenant registry rather than the shared filesystem — so
    a tenant only sees files their own ingest run has registered. The
    search filter does a case-insensitive ILIKE against ``title``,
    ``folder``, and a JSONB ``tags`` containment match.
    """

    _ = user  # auth side-effect; the tenant resolution already happened.

    base = select(Document).where(
        Document.tenant_id == tenant.id,
        Document.archived_at.is_(None),
    )
    if search:
        needle = f"%{search}%"
        base = base.where(
            or_(
                Document.title.ilike(needle),
                Document.folder.ilike(needle),
                cast(Document.tags, Text).ilike(needle),
            )
        )

    docs_total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    # Phase 32.2 — surface products (the e-commerce catalogue) alongside
    # vault notes so the Documents view reflects every artifact the tenant
    # has registered. Both queries are tenant-scoped; we union the row
    # dicts in Python and paginate after concatenation. Catalogue sizes
    # stay small enough (≤ a few hundred per tenant) that this is fine;
    # if it grows, swap for a proper SQL UNION ALL + window pagination.
    products_query = select(Product).where(Product.tenant_id == tenant.id)
    if search:
        needle = f"%{search}%"
        products_query = products_query.where(
            or_(
                Product.name.ilike(needle),
                Product.description.ilike(needle),
            )
        )

    products_total = (
        await db.execute(
            select(func.count()).select_from(products_query.subquery())
        )
    ).scalar_one()

    total = int(docs_total) + int(products_total)

    docs_rows = (
        await db.execute(base.order_by(Document.indexed_at.desc()))
    ).scalars().all()
    product_rows = (
        await db.execute(products_query.order_by(Product.updated_at.desc()))
    ).scalars().all()

    combined: list[dict] = (
        [_document_to_dict(d) for d in docs_rows]
        + [_product_to_doc_dict(p) for p in product_rows]
    )
    combined.sort(key=lambda r: r.get("modified") or 0.0, reverse=True)

    start = (page - 1) * limit
    items = combined[start : start + limit]
    pages = max(1, (total + limit - 1) // limit)
    return {"items": items, "total": total, "pages": pages}


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
async def archive_documents(
    req: ArchiveRequest,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Soft-delete: flip ``archived_at`` for each matching Document row in
    the active tenant, move the file into ``04 - Archive/``, and purge
    its Qdrant chunks. Per-path errors are collected rather than aborting
    the batch."""
    _ = user
    root = _vault_root()
    archived: list[dict] = []
    failed: list[dict] = []
    purged = 0
    now = datetime.now(timezone.utc)

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

        # Flip archived_at on the matching Document row for this tenant.
        stmt = select(Document).where(
            Document.tenant_id == tenant.id,
            Document.file == orig_rel,
        )
        doc = (await db.execute(stmt)).scalar_one_or_none()
        if doc is not None:
            doc.archived_at = now

        # Best-effort vector purge — tenant-scoped so a sibling tenant
        # ingesting the same path keeps its chunks.
        try:
            delete_vectors_for_file(orig_rel, tenant_slug=tenant.slug)
            purged += 1
        except Exception as exc:  # noqa: BLE001 — defensive; helper itself catches
            log.warning("vector purge failed for %s: %s", orig_rel, exc)

        archived.append({"path": rel_path, "archived_path": new_rel})

    await db.commit()
    return {"archived": archived, "failed": failed, "vectors_purged": purged}


# ── Vault reconciliation (orphan cleanup) ──────────────────────────────────

def _qdrant_indexed_files(tenant_slug: str) -> set[str]:
    """Scroll the collection (tenant-filtered) and collect every unique
    ``payload.file`` value owned by the active tenant."""
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
            scroll_filter=_tenant_filter(tenant_slug),
        )
        for p in points:
            payload = p.payload or {}
            f = payload.get("file")
            if isinstance(f, str) and f:
                files.add(f)
        if next_offset is None:
            break
    return files


def _qdrant_index_summary(tenant_slug: str) -> dict[str, dict[str, int]]:
    """Return ``{rel_path: {"chunks": N, "est_tokens": M}}`` for the active
    tenant from a single scroll."""
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
            scroll_filter=_tenant_filter(tenant_slug),
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
async def index_summary(
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    """Per-file chunk count + token estimate for the active tenant from the
    live Qdrant collection."""
    _ = user
    try:
        summary = _qdrant_index_summary(tenant.slug)
    except Exception as exc:  # noqa: BLE001 — UI should still load if Qdrant is down
        log.warning("index_summary scroll failed: %s", exc)
        return {"summary": {}, "total_chunks": 0, "available": False}

    total_chunks = sum(v["chunks"] for v in summary.values())
    return {"summary": summary, "total_chunks": total_chunks, "available": True}


@router.post("/documents/reconcile")
async def reconcile_vault(
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Find Qdrant points (owned by the active tenant) whose file no longer
    has a live ``app.documents`` row in this tenant.

    "Live" means a row with ``archived_at IS NULL``. Archived files are
    intentionally treated as orphans here — their Qdrant chunks should
    have been purged during the archive call; reconcile is the cleanup
    pass that catches any leaks.
    """
    _ = user

    try:
        qdrant_files = _qdrant_indexed_files(tenant.slug)
    except Exception as exc:
        log.exception("qdrant scroll failed during reconcile")
        raise HTTPException(status_code=502, detail=f"Qdrant unreachable: {exc}") from exc

    stmt = select(Document.file).where(
        and_(
            Document.tenant_id == tenant.id,
            Document.archived_at.is_(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    live_files = {row[0] for row in rows}

    orphans = sorted(qdrant_files - live_files)
    purged = 0
    for orphan in orphans:
        try:
            delete_vectors_for_file(orphan, tenant_slug=tenant.slug)
            purged += 1
        except Exception as exc:  # noqa: BLE001 — keep going on individual failures
            log.warning("vector purge failed for orphan %s: %s", orphan, exc)

    return {
        "qdrant_files": len(qdrant_files),
        "active_files": len(live_files),
        "orphans": orphans,
        "purged": purged,
    }
