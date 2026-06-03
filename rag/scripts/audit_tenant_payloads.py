"""Phase 46 — Qdrant tenant-payload audit script.

Scroll the entire ``nexus-vault`` collection and assert every point
payload carries a non-empty ``tenant_id``.  Orphan point IDs (missing or
empty ``tenant_id``) are printed and the script exits with a non-zero
code so CI / a manual run can distinguish:

    exit 0 — no orphans found; collection is clean.
    exit 1 — one or more orphan points found; investigate.
    exit 2 — Qdrant unreachable or env misconfigured; cannot assess.

This script is **read-only** — it never mutates or deletes any point.

Usage (from repo root):
    uv run python rag/scripts/audit_tenant_payloads.py

Or from inside the ``rag/`` directory:
    uv run python scripts/audit_tenant_payloads.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

_log = logging.getLogger("phase46.audit")

_BATCH_SIZE = 512
_SHOW_FIRST_N = 20


def _build_client():  # type: ignore[return]
    """Build an AsyncQdrantClient from environment variables.

    Mirrors the pattern used by ``rag/retrieval/dense.py`` — reads
    ``QDRANT_URL`` and optionally ``QDRANT_API_KEY``.  Does NOT import
    ``rag.config`` to stay runnable as a standalone script without the
    full app bootstrap.
    """
    url = os.environ.get("QDRANT_URL", "").strip()
    if not url:
        print(
            "ERROR: QDRANT_URL env var is not set. "
            "Set it to the Qdrant instance URL (e.g. http://127.0.0.1:6333) "
            "before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)

    from qdrant_client import (
        AsyncQdrantClient,
    )  # import here; not needed at module level

    api_key = os.environ.get("QDRANT_API_KEY") or None
    return AsyncQdrantClient(url=url, api_key=api_key)


async def _audit() -> tuple[int, list[str | int]]:
    """Scroll the entire collection; return (total_scanned, orphan_ids).

    Raises on network errors so the caller can exit with code 2.
    """
    collection = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
    client = _build_client()
    total = 0
    orphans: list[str | int] = []

    try:
        offset = None
        while True:
            batch, next_offset = await client.scroll(
                collection_name=collection,
                limit=_BATCH_SIZE,
                offset=offset,
                with_payload=["tenant_id"],
                with_vectors=False,
            )
            for point in batch:
                total += 1
                payload = dict(point.payload or {})
                tenant_id = payload.get("tenant_id")
                if not tenant_id or not str(tenant_id).strip():
                    orphans.append(point.id)
            if next_offset is None:
                break
            offset = next_offset
    finally:
        await client.close()

    return total, orphans


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        total, orphans = asyncio.run(_audit())
    except SystemExit:
        raise
    except Exception as exc:
        print(
            f"ERROR: Qdrant unreachable or audit failed: {exc}",
            file=sys.stderr,
        )
        return 2

    orphan_count = len(orphans)
    print("Phase 46 tenant-payload audit")
    print(f"  total points scanned : {total}")
    print(f"  orphan points (no tenant_id) : {orphan_count}")

    if orphan_count > 0:
        first_n = orphans[:_SHOW_FIRST_N]
        print(f"  first {min(_SHOW_FIRST_N, orphan_count)} orphan IDs:")
        for pid in first_n:
            print(f"    {pid}")
        if orphan_count > _SHOW_FIRST_N:
            print(f"    ... and {orphan_count - _SHOW_FIRST_N} more")
        print(
            "\nREMEDIATION: Run rag/scripts/cleanup_phase31_leak.py to delete "
            "orphan points, then re-run this audit to confirm clean."
        )
        return 1

    print("  result: CLEAN — all points carry a tenant_id.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
