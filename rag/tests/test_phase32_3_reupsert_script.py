"""Phase 32.3 — reupsert script routes products through the live sync.

Validates the script's per-row branching without touching Postgres or
Qdrant: ``_iter_products`` and ``upsert_product_to_qdrant`` are patched
so the assertions run against the loop logic alone.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from rag.scripts import reupsert_products


def _product(
    *, is_active: bool = True, quantity: int = 5, slug: str = "p"
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=f"Product {slug}",
        slug=slug,
        description="",
        price_cents=1000,
        currency="USD",
        is_active=is_active,
        quantity=quantity,
        url=None,
    )


def test_reupsert_all_routes_each_product_through_sync(monkeypatch) -> None:
    seen: list[tuple[uuid.UUID, str]] = []

    async def fake_iter(db, *, tenant_slug):
        del db, tenant_slug
        return [
            (_product(slug="a"), "tenant-a"),
            (_product(slug="b"), "tenant-a"),
            (_product(slug="c"), "tenant-b"),
        ]

    async def fake_upsert(product, *, tenant_slug):
        seen.append((product.id, tenant_slug))

    monkeypatch.setattr(reupsert_products, "_iter_products", fake_iter)
    monkeypatch.setattr(reupsert_products, "upsert_product_to_qdrant", fake_upsert)
    monkeypatch.setattr(
        reupsert_products,
        "get_sessionmaker",
        lambda: lambda: _NullSession(),
    )

    summary = asyncio.run(reupsert_products.reupsert_all())
    assert summary.total == 3
    assert summary.upserted == 3
    assert summary.failed == 0
    assert len(seen) == 3
    assert {s[1] for s in seen} == {"tenant-a", "tenant-b"}


def test_reupsert_all_counts_inactive_and_out_of_stock_skips(monkeypatch) -> None:
    async def fake_iter(db, *, tenant_slug):
        del db, tenant_slug
        return [
            (_product(is_active=False, slug="x"), "t"),
            (_product(quantity=0, slug="y"), "t"),
            (_product(slug="z"), "t"),
        ]

    async def fake_upsert(product, *, tenant_slug):
        del product, tenant_slug

    monkeypatch.setattr(reupsert_products, "_iter_products", fake_iter)
    monkeypatch.setattr(reupsert_products, "upsert_product_to_qdrant", fake_upsert)
    monkeypatch.setattr(
        reupsert_products,
        "get_sessionmaker",
        lambda: lambda: _NullSession(),
    )

    summary = asyncio.run(reupsert_products.reupsert_all())
    assert summary.skipped_inactive == 1
    assert summary.skipped_out_of_stock == 1
    assert summary.upserted == 1
    assert summary.failed == 0


def test_reupsert_all_records_failures_without_aborting(monkeypatch) -> None:
    async def fake_iter(db, *, tenant_slug):
        del db, tenant_slug
        return [
            (_product(slug="ok-1"), "t"),
            (_product(slug="boom"), "t"),
            (_product(slug="ok-2"), "t"),
        ]

    async def fake_upsert(product, *, tenant_slug):
        if product.slug == "boom":
            raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(reupsert_products, "_iter_products", fake_iter)
    monkeypatch.setattr(reupsert_products, "upsert_product_to_qdrant", fake_upsert)
    monkeypatch.setattr(
        reupsert_products,
        "get_sessionmaker",
        lambda: lambda: _NullSession(),
    )

    summary = asyncio.run(reupsert_products.reupsert_all())
    assert summary.failed == 1
    assert summary.upserted == 2
    assert summary.total == 3


def test_reupsert_all_tenant_scope_passes_through(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    async def fake_iter(db, *, tenant_slug):
        del db
        captured["slug"] = tenant_slug
        return []

    monkeypatch.setattr(reupsert_products, "_iter_products", fake_iter)
    monkeypatch.setattr(
        reupsert_products,
        "get_sessionmaker",
        lambda: lambda: _NullSession(),
    )

    asyncio.run(reupsert_products.reupsert_all(tenant_slug="cozy-downloads"))
    assert captured["slug"] == "cozy-downloads"


class _NullSession:
    """Async context manager that yields itself — keeps ``async with`` happy
    without spinning up an asyncpg connection."""

    async def __aenter__(self) -> "_NullSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
