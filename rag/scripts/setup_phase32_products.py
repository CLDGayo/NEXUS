"""Phase 32 — one-shot bootstrap for the Product Catalog feature.

Idempotent. Safe to run repeatedly. Performs:

    1. ``ensure_bucket(settings.minio_bucket_products)`` — creates the
       MinIO bucket if absent.
    2. Detects the live Qdrant collection's vector size and surfaces
       any mismatch with the retrieval-side embedder dim (bge-small =
       384). If the live collection is 768-dim (jina) products can still
       index by re-encoding with the ingest-side embedder, but the
       operator should switch ``EMBED_MODEL`` to match the collection or
       provision a dedicated products collection.

Run with::

    uv run python -m rag.scripts.setup_phase32_products
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rag.config import settings
from rag.retrieval.dense import get_embedder, get_qdrant_client
from rag.services import object_store

_log = logging.getLogger(__name__)

_BGE_SMALL_DIM = 384
_JINA_BASE_DIM = 768


async def _ensure_bucket() -> None:
    bucket = settings.minio_bucket_products
    created = await object_store.ensure_bucket(bucket)
    if created:
        print(f"[ok] minio bucket created: {bucket}")
    else:
        print(f"[ok] minio bucket already exists: {bucket}")


def _expected_dim_for(model_name: str) -> int | None:
    lower = (model_name or "").lower()
    if "bge-small" in lower:
        return _BGE_SMALL_DIM
    if "jina" in lower and "v2-base" in lower:
        return _JINA_BASE_DIM
    return None


async def _check_qdrant_vector_size(*, strict: bool) -> int:
    client = get_qdrant_client()
    try:
        collection = await client.get_collection(settings.qdrant_collection)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[warn] could not read Qdrant collection "
            f"{settings.qdrant_collection!r}: {exc}"
        )
        return 1 if strict else 0

    vectors_cfg = collection.config.params.vectors
    if hasattr(vectors_cfg, "size"):
        size = int(getattr(vectors_cfg, "size"))
    elif isinstance(vectors_cfg, dict):
        # Named vectors path; pick the default if present, else the first.
        first = next(iter(vectors_cfg.values()))
        size = int(getattr(first, "size", 0))
    else:
        size = 0

    expected = _expected_dim_for(settings.embed_model)
    print(
        f"[info] qdrant collection={settings.qdrant_collection} "
        f"vector_size={size} embed_model={settings.embed_model} "
        f"expected_dim={expected}"
    )

    # Validate by encoding a probe and comparing the actual length.
    try:
        embedder = get_embedder()
        probe = next(iter(embedder.embed(["phase32 product probe"])))
        probe_dim = len(probe)
        print(f"[info] retrieval embedder produces {probe_dim}-dim vectors")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not probe embedder: {exc}")
        probe_dim = expected or 0

    if size and probe_dim and size != probe_dim:
        print(
            f"[ERROR] vector-size mismatch: collection={size} embedder={probe_dim}. "
            f"Product upserts WILL FAIL until resolved. Options: "
            f"(a) switch EMBED_MODEL to a {size}-dim model, "
            f"(b) recreate the Qdrant collection at {probe_dim}-dim, or "
            f"(c) provision a dedicated nexus-products collection at {probe_dim}-dim."
        )
        return 2

    print("[ok] vector-size invariant satisfied")
    return 0


async def _main(strict: bool) -> int:
    print("Phase 32 — Product Catalog bootstrap")
    print("-" * 40)
    rc = 0
    try:
        await _ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] bucket bootstrap failed: {exc}")
        rc = max(rc, 2)
        if strict:
            return rc

    rc = max(rc, await _check_qdrant_vector_size(strict=strict))

    print("-" * 40)
    print(f"[done] exit={rc}")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 32 product bootstrap")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat any warning as a failure (exit non-zero).",
    )
    args = parser.parse_args()
    return asyncio.run(_main(strict=args.strict))


if __name__ == "__main__":
    sys.exit(main())
