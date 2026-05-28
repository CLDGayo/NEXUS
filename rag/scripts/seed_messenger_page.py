"""Phase 32.3 — bind a Facebook Page id to its owning tenant.

The Messenger inbound webhook resolves the owning tenant from the
``page_id`` field of every coalesced Meta envelope. An unmapped page is
dropped with a ``messenger.event.no_tenant_mapping`` log — silent for
the customer, by design (Phase 29 closed a cross-tenant leak by
refusing to default).

This script is the operator path for adding rows to
``app.messenger_page_tenants``. Idempotent: re-running with the same
``(facebook_page_id, tenant_slug)`` pair is a no-op; running with a
different tenant for the same page rebinds it.

Usage::

    # List tenants to find the slug.
    uv run python -m rag.scripts.seed_messenger_page --list-tenants

    # Bind a page (FB Page ID from Meta Business Suite → Page → About).
    uv run python -m rag.scripts.seed_messenger_page \\
        --tenant-slug cozy-downloads \\
        --page-id 107123456789012
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import dispose_engine, get_sessionmaker
from rag.database.models import MessengerPageTenant, Tenant

_log = logging.getLogger("phase32_3.seed_messenger_page")


@dataclass(frozen=True)
class SeedResult:
    facebook_page_id: str
    tenant_slug: str
    rebind: bool


async def _resolve_tenant(db: AsyncSession, slug: str) -> Tenant | None:
    stmt = select(Tenant).where(Tenant.slug == slug)
    return (await db.execute(stmt)).scalar_one_or_none()


async def seed(*, facebook_page_id: str, tenant_slug: str) -> SeedResult:
    """Upsert the page → tenant mapping. Returns a receipt for printing."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        tenant = await _resolve_tenant(db, tenant_slug)
        if tenant is None:
            raise LookupError(f"tenant not found: slug={tenant_slug!r}")

        existing_stmt = select(MessengerPageTenant).where(
            MessengerPageTenant.facebook_page_id == facebook_page_id
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        rebind = existing is not None and existing.tenant_id != tenant.id

        stmt = (
            pg_insert(MessengerPageTenant)
            .values(facebook_page_id=facebook_page_id, tenant_id=tenant.id)
            .on_conflict_do_update(
                index_elements=[MessengerPageTenant.facebook_page_id],
                set_={"tenant_id": tenant.id},
            )
        )
        await db.execute(stmt)
        await db.commit()

    return SeedResult(
        facebook_page_id=facebook_page_id,
        tenant_slug=tenant_slug,
        rebind=rebind,
    )


async def list_tenants() -> list[tuple[str, str]]:
    """Return ``[(slug, name), ...]`` for every tenant row."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        rows = (
            await db.execute(select(Tenant.slug, Tenant.name).order_by(Tenant.slug))
        ).all()
    return [(row[0], row[1]) for row in rows]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag.scripts.seed_messenger_page",
        description=(
            "Bind a Facebook Page id to its owning tenant so the Messenger "
            "webhook can route inbound events. Idempotent."
        ),
        epilog=(
            "Page id source: Meta Business Suite → Settings → Pages → your "
            "page → About → Page ID."
        ),
    )
    parser.add_argument(
        "--tenant-slug",
        dest="tenant_slug",
        help="Slug of the owning tenant (see --list-tenants).",
    )
    parser.add_argument(
        "--page-id",
        dest="page_id",
        help="Facebook Page id (numeric string).",
    )
    parser.add_argument(
        "--list-tenants",
        action="store_true",
        help="Print every tenant slug + display name, then exit.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable INFO logging."
    )
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        if args.list_tenants:
            rows = asyncio.run(list_tenants())
            if not rows:
                print("(no tenants)")
                return 0
            slug_w = max(len(slug) for slug, _ in rows)
            for slug, name in rows:
                print(f"  {slug:<{slug_w}}  {name}")
            return 0

        if not args.tenant_slug or not args.page_id:
            parser.error(
                "--tenant-slug and --page-id are required (or use --list-tenants)"
            )

        try:
            result = asyncio.run(
                seed(
                    facebook_page_id=args.page_id,
                    tenant_slug=args.tenant_slug,
                )
            )
        except LookupError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        action = "rebound" if result.rebind else "bound"
        print(
            f"{action} facebook_page_id={result.facebook_page_id} "
            f"tenant_slug={result.tenant_slug}"
        )
        return 0
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    sys.exit(main())
