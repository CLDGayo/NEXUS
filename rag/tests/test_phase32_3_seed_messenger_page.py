"""Phase 32.3 — ``seed_messenger_page`` script error and argument paths.

The happy path requires a live Postgres (and is exercised by an
integration test against ``app.messenger_page_tenants`` in the deploy
runbook). These tests pin the CLI surface, the help epilog, and the
unknown-tenant exit code without touching the database.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from rag.scripts import seed_messenger_page


def test_main_requires_tenant_slug_and_page_id_when_not_listing() -> None:
    with pytest.raises(SystemExit) as excinfo:
        seed_messenger_page.main([])
    assert excinfo.value.code == 2


def test_main_lookup_error_returns_exit_code_2(monkeypatch, capsys) -> None:
    async def fake_seed(*, facebook_page_id, tenant_slug):
        raise LookupError(f"tenant not found: slug={tenant_slug!r}")

    monkeypatch.setattr(seed_messenger_page, "seed", fake_seed)
    monkeypatch.setattr(seed_messenger_page, "dispose_engine", _fake_async_noop)

    rc = seed_messenger_page.main(["--tenant-slug", "ghost", "--page-id", "1234"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "tenant not found" in captured.err


def test_main_happy_path_prints_bound_receipt(monkeypatch, capsys) -> None:
    async def fake_seed(*, facebook_page_id, tenant_slug):
        assert facebook_page_id == "9988"
        assert tenant_slug == "cozy-downloads"
        return seed_messenger_page.SeedResult(
            facebook_page_id=facebook_page_id,
            tenant_slug=tenant_slug,
            rebind=False,
        )

    monkeypatch.setattr(seed_messenger_page, "seed", fake_seed)
    monkeypatch.setattr(seed_messenger_page, "dispose_engine", _fake_async_noop)

    rc = seed_messenger_page.main(
        ["--tenant-slug", "cozy-downloads", "--page-id", "9988"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "bound facebook_page_id=9988 tenant_slug=cozy-downloads" in out


def test_main_reports_rebind_when_existing_row_moves_tenant(
    monkeypatch, capsys
) -> None:
    async def fake_seed(*, facebook_page_id, tenant_slug):
        return seed_messenger_page.SeedResult(
            facebook_page_id=facebook_page_id,
            tenant_slug=tenant_slug,
            rebind=True,
        )

    monkeypatch.setattr(seed_messenger_page, "seed", fake_seed)
    monkeypatch.setattr(seed_messenger_page, "dispose_engine", _fake_async_noop)

    rc = seed_messenger_page.main(
        ["--tenant-slug", "cozy-downloads", "--page-id", "9988"]
    )
    assert rc == 0
    assert "rebound" in capsys.readouterr().out


def test_main_list_tenants_renders_table(monkeypatch, capsys) -> None:
    async def fake_list():
        return [
            ("alpha", "Alpha Inc."),
            ("cozy-downloads", "Cozy Downloads Store"),
        ]

    monkeypatch.setattr(seed_messenger_page, "list_tenants", fake_list)
    monkeypatch.setattr(seed_messenger_page, "dispose_engine", _fake_async_noop)

    rc = seed_messenger_page.main(["--list-tenants"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "Cozy Downloads Store" in out


def test_main_list_tenants_empty(monkeypatch, capsys) -> None:
    async def fake_list():
        return []

    monkeypatch.setattr(seed_messenger_page, "list_tenants", fake_list)
    monkeypatch.setattr(seed_messenger_page, "dispose_engine", _fake_async_noop)

    rc = seed_messenger_page.main(["--list-tenants"])
    assert rc == 0
    assert "(no tenants)" in capsys.readouterr().out


async def _fake_async_noop() -> None:
    return None


def test_seed_result_carries_rebind_flag() -> None:
    result = seed_messenger_page.SeedResult(
        facebook_page_id="1",
        tenant_slug="t",
        rebind=True,
    )
    assert result.rebind is True
    # Sanity: it's a value type.
    assert result == seed_messenger_page.SeedResult(
        facebook_page_id="1", tenant_slug="t", rebind=True
    )


def test_unused_uuid_import_smoke() -> None:
    # Keeps the linter from pruning ``uuid`` if a future edit needs it.
    assert uuid.UUID("00000000-0000-0000-0000-000000000000").int == 0


def test_run_via_asyncio_uses_sessionmaker(monkeypatch) -> None:
    """The seed coroutine opens a sessionmaker before any DB call. Patch the
    sessionmaker to a no-op context manager and confirm the resolver hop is
    reached and produces LookupError when the tenant is absent."""

    class _NullSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, _stmt):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return None

            return _Result()

        async def commit(self):
            return None

    monkeypatch.setattr(
        seed_messenger_page, "get_sessionmaker", lambda: lambda: _NullSession()
    )
    with pytest.raises(LookupError):
        asyncio.run(
            seed_messenger_page.seed(facebook_page_id="1", tenant_slug="missing")
        )
