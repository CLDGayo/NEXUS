"""Phase 32.3 — backfill the enriched product payload into Qdrant.

Phase 32 shipped a thin product payload (``kind``, ``product_id``,
``tenant_id``, ``name``, ...). Phase 32.3 added ``file``, ``title``,
``text``, ``heading_path``, ``folder``, ``source_kind`` so the Documents
UI and citation renderer can treat products as first-class documents.
Existing points in production retain the thin payload until a re-upsert
runs.

This script iterates ``app.products`` and re-upserts every row through
``upsert_product_to_qdrant``. The point id is ``uuid5(NAMESPACE_PRODUCTS,
product.id)`` — deterministic, so the upsert overwrites the existing
point in place rather than minting a duplicate.

Usage::

    uv run python -m rag.scripts.reupsert_products
    uv run python -m rag.scripts.reupsert_products --tenant cozy-downloads
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import dispose_engine, get_sessionmaker
from rag.database.models import Product, Tenant
from rag.products.sync import upsert_product_to_qdrant

_log = logging.getLogger("phase32_3.reupsert")


@dataclass(frozen=True)
class ReupsertSummary:
    upserted: int
    skipped_inactive: int
    skipped_out_of_stock: int
    failed: int

    @property
    def total(self) -> int:
        return (
            self.upserted
            + self.skipped_inactive
            + self.skipped_out_of_stock
            + self.failed
        )


async def _iter_products(
    db: AsyncSession, *, tenant_slug: str | None
) -> list[tuple[Product, str]]:
    """Yield ``(product, tenant_slug)`` pairs for the active scope."""
    stmt = select(Product, Tenant.slug).join(Tenant, Tenant.id == Product.tenant_id)
    if tenant_slug is not None:
        stmt = stmt.where(Tenant.slug == tenant_slug)
    stmt = stmt.order_by(Tenant.slug, Product.updated_at.desc())
    rows = (await db.execute(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def reupsert_all(*, tenant_slug: str | None = None) -> ReupsertSummary:
    """Run the backfill. Returns a summary counter for logging.

    Idempotent: ``upsert_product_to_qdrant`` is safe to call repeatedly
    on the same product because the point id is deterministic.
    """
    sessionmaker = get_sessionmaker()
    upserted = 0
    skipped_inactive = 0
    skipped_oos = 0
    failed = 0

    async with sessionmaker() as db:
        products = await _iter_products(db, tenant_slug=tenant_slug)
        for product, slug in products:
            if not product.is_active:
                skipped_inactive += 1
                _log.info(
                    "reupsert.skip product_id=%s tenant=%s reason=inactive",
                    product.id,
                    slug,
                )
            elif product.quantity <= 0:
                skipped_oos += 1
                _log.info(
                    "reupsert.skip product_id=%s tenant=%s reason=out_of_stock",
                    product.id,
                    slug,
                )

            try:
                await upsert_product_to_qdrant(product, tenant_slug=slug)
            except Exception as exc:  # noqa: BLE001 — keep going, log per-row
                failed += 1
                _log.warning(
                    "reupsert.failed product_id=%s tenant=%s detail=%s",
                    product.id,
                    slug,
                    exc,
                )
                continue

            if product.is_active and product.quantity > 0:
                upserted += 1

    return ReupsertSummary(
        upserted=upserted,
        skipped_inactive=skipped_inactive,
        skipped_out_of_stock=skipped_oos,
        failed=failed,
    )


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag.scripts.reupsert_products",
        description=(
            "Re-upsert every product into Qdrant with the Phase 32.3 enriched "
            "payload (adds file/title/text/heading_path/folder/source_kind)."
        ),
    )
    parser.add_argument(
        "--tenant",
        dest="tenant_slug",
        default=None,
        help="Restrict the backfill to a single tenant slug.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable INFO logging."
    )
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    async def _run() -> ReupsertSummary:
        try:
            return await reupsert_all(tenant_slug=args.tenant_slug)
        finally:
            await dispose_engine()

    summary = asyncio.run(_run())

    print("phase32.3 reupsert summary:")
    print(f"  scope                {args.tenant_slug or 'all-tenants'}")
    print(f"  total                {summary.total}")
    print(f"  upserted             {summary.upserted}")
    print(f"  skipped_inactive     {summary.skipped_inactive}")
    print(f"  skipped_out_of_stock {summary.skipped_out_of_stock}")
    print(f"  failed               {summary.failed}")
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
