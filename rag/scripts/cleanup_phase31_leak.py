"""Phase 31 — Qdrant leak scrubber.

The Architect's audit surfaced two classes of garbage in the live Qdrant
collection that pre-date the Phase 31 lockdown:

    1. Source-tree files (``.venv/...``, ``__pycache__/...``,
       ``node_modules/...``) that were swept in by an early ingest run
       whose skip set was thinner than today's
       :data:`rag.ingest_v2.pipeline._VAULT_SKIP_DIRS`.
    2. Points without a ``tenant_id`` payload at all — minted before
       Phase 29 strict tenancy landed. After the Phase 31 rewrite of
       ``/api/documents``, these are unattributable and unsafe to serve
       to anyone, so they get deleted.

Run once after the schema migration applies and a reindex has populated
``app.documents`` / ``app.document_links``. Idempotent — re-running on a
clean collection is a no-op.

Usage:
    uv run python -m rag.scripts.cleanup_phase31_leak [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from collections import Counter

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointIdsList

_log = logging.getLogger("phase31.cleanup")

# Match anywhere in the relative file path. The leading group catches
# the bare-root case (path stored as ".venv/foo.py" rather than
# "subdir/.venv/foo.py").
_LEAK_DIR_RE = re.compile(
    r"(?:^|/)(?:\.venv|__pycache__|node_modules)(?:/|$)"
)


def _is_leak_payload(payload: dict | None) -> str | None:
    """Return the leak classification for one point, or ``None`` if clean."""

    if not payload:
        return "missing_payload"
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        return "missing_tenant_id"
    file = payload.get("file")
    if isinstance(file, str) and _LEAK_DIR_RE.search(file):
        return "leaked_source_tree"
    return None


def _build_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY") or None,
    )


async def scrub(*, dry_run: bool, batch_size: int = 512) -> dict[str, int]:
    """Scroll the active collection, classify every point, delete the
    leaky ones. Returns a per-class counter for logging."""

    collection = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
    client = _build_client()
    counter: Counter[str] = Counter()
    leaked_ids: list[str | int] = []

    try:
        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=collection,
                limit=batch_size,
                with_payload=["file", "tenant_id"],
                with_vectors=False,
                offset=offset,
            )
            for point in points:
                classification = _is_leak_payload(point.payload)
                if classification is None:
                    counter["clean"] += 1
                    continue
                counter[classification] += 1
                leaked_ids.append(point.id)
            if offset is None:
                break

        if leaked_ids and not dry_run:
            # Delete in chunks so a single API call does not hit Qdrant's
            # body-size limit for very large leaks.
            for i in range(0, len(leaked_ids), batch_size):
                await client.delete(
                    collection_name=collection,
                    points_selector=PointIdsList(
                        points=leaked_ids[i : i + batch_size]
                    ),
                )
    finally:
        await client.close()

    counter["deleted"] = 0 if dry_run else len(leaked_ids)
    counter["would_delete"] = len(leaked_ids) if dry_run else 0
    return dict(counter)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag.scripts.cleanup_phase31_leak",
        description="Scrub Phase 31 Qdrant leaks (.venv/__pycache__/missing tenant).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and report without deleting anything.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable INFO logging."
    )
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if "QDRANT_URL" not in os.environ:
        print(
            "ERROR: QDRANT_URL env var not set; refusing to operate on an "
            "implicit default.",
            file=sys.stderr,
        )
        return 2

    result = asyncio.run(scrub(dry_run=args.dry_run))
    print("phase31 cleanup summary:")
    for key in sorted(result):
        print(f"  {key:20s} {result[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
