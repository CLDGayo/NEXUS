"""Phase 31 — Alembic migration 0005 structure + backfill helpers."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0005_phase31_security_and_docs.py"
    )
    spec = importlib.util.spec_from_file_location("_phase31_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chains_to_phase30(migration_module) -> None:
    assert migration_module.revision == "0005_phase31_security_and_docs"
    assert migration_module.down_revision == "0004_phase30_sqlite_to_pg"


def test_canonical_bootstrap_slug(migration_module) -> None:
    assert migration_module.CANONICAL_BOOTSTRAP_SLUG == "cozy-downloads-store"


def test_pick_bootstrap_tenant_prefers_canonical_slug(migration_module) -> None:
    canon_uuid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    older_uuid = uuid.UUID("11111111-1111-1111-1111-111111111111")

    class _Bind:
        def __init__(self, has_canon: bool) -> None:
            self._has_canon = has_canon

        def execute(self, stmt, params=None):  # noqa: ANN001
            sql = str(stmt)
            if "WHERE slug" in sql:
                hit = (
                    [(canon_uuid,)] if self._has_canon else []
                )
                return _Result(hit)
            return _Result([(older_uuid,)])

    class _Result:
        def __init__(self, rows): self._rows = rows  # noqa: E704

        def first(self): return self._rows[0] if self._rows else None  # noqa: E704

    bind_with_canon = _Bind(has_canon=True)
    assert (
        migration_module._pick_bootstrap_tenant(bind_with_canon) == canon_uuid
    )
    bind_no_canon = _Bind(has_canon=False)
    assert (
        migration_module._pick_bootstrap_tenant(bind_no_canon) == older_uuid
    )


def test_pick_bootstrap_tenant_returns_none_on_empty(migration_module) -> None:
    class _EmptyBind:
        def execute(self, stmt, params=None):  # noqa: ANN001
            return _EmptyResult()

    class _EmptyResult:
        def first(self): return None  # noqa: E704

    assert migration_module._pick_bootstrap_tenant(_EmptyBind()) is None


def test_downgrade_callable(migration_module) -> None:
    # Just confirm the symbol exists and is callable — full reversibility
    # is exercised by the integration suite that talks to a real Postgres.
    assert callable(migration_module.downgrade)
    assert callable(migration_module.upgrade)
