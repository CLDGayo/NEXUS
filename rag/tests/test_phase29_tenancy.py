"""Phase 29 — strict multi-tenancy guard + tenant router.

Covers:
    * ``slugify_tenant_name`` edge cases (CJK strip, collapse, empty).
    * ``get_current_tenant`` — 400 on missing header, 403 on non-member.
    * ``rag.orchestrator.nodes._tenant_filter`` — raises when state lacks
      ``tenant_id`` so a missed surface adapter cannot silently fall back
      to the legacy unscoped retrieval.
    * ``_compose_filter`` from the graph arm always carries the tenant
      predicate, even when the seed set is empty.

Integration-style end-to-end tests (POST /api/tenants, register-then-list)
require Postgres and are exercised separately in CI; this file stays
unit-scoped so it runs in the in-memory test environment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from qdrant_client.models import FieldCondition, Filter, MatchValue


# --------------------------------------------------------------------------
# slugify_tenant_name
# --------------------------------------------------------------------------


def test_slugify_lowercases_and_replaces_spaces() -> None:
    from rag.auth.tenant import slugify_tenant_name

    assert slugify_tenant_name("Hunter") == "hunter"
    assert slugify_tenant_name("Akiro Collectibles") == "akiro-collectibles"


def test_slugify_strips_cjk_to_ascii() -> None:
    from rag.auth.tenant import slugify_tenant_name

    # 東京ハンター collapses; surviving ASCII is hyphenated.
    assert slugify_tenant_name("Akiro Collectibles 東京ハンター") == "akiro-collectibles"


def test_slugify_collapses_repeated_hyphens() -> None:
    from rag.auth.tenant import slugify_tenant_name

    assert slugify_tenant_name("foo---bar") == "foo-bar"
    assert slugify_tenant_name("a  b  c") == "a-b-c"


def test_slugify_empty_input_returns_default() -> None:
    from rag.auth.tenant import slugify_tenant_name

    assert slugify_tenant_name("") == "tenant"
    assert slugify_tenant_name("   ") == "tenant"
    assert slugify_tenant_name("///") == "tenant"


def test_slugify_clamps_to_max_length() -> None:
    from rag.auth.tenant import slugify_tenant_name

    out = slugify_tenant_name("a" * 500)
    assert len(out) == 120


# --------------------------------------------------------------------------
# get_current_tenant
# --------------------------------------------------------------------------


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _FakeTenantRow:
    def __init__(self, slug: str) -> None:
        self.id = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
        self.name = slug.capitalize()
        self.slug = slug
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


class _FakeTenantUser:
    def __init__(self, role: str = "owner") -> None:
        self.role = role


class _StubSession:
    """AsyncSession stand-in. ``links`` maps (tenant_id, user_id) → link or
    ``None``; ``tenants`` maps tenant_id → Tenant or ``None``."""

    def __init__(
        self,
        *,
        links: dict | None = None,
        tenants: dict | None = None,
    ) -> None:
        self._links = links or {}
        self._tenants = tenants or {}

    async def get(self, model, key):  # noqa: ANN001 — duck-typed for tests
        name = model.__name__
        if name == "TenantUser":
            return self._links.get(key)
        if name == "Tenant":
            return self._tenants.get(key)
        return None


class _StubRequest:
    def __init__(self) -> None:
        self.state = type("S", (), {})()


@pytest.mark.asyncio
async def test_get_current_tenant_400_when_header_missing() -> None:
    from rag.auth.tenant import get_current_tenant

    user = _FakeUser()
    session = _StubSession()

    with pytest.raises(HTTPException) as exc:
        await get_current_tenant(
            request=_StubRequest(),
            x_tenant_id=None,
            user=user,
            db=session,
        )
    assert exc.value.status_code == 400
    assert "X-Tenant-ID" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_get_current_tenant_403_when_user_not_in_tenant() -> None:
    from rag.auth.tenant import get_current_tenant

    user = _FakeUser()
    other_tenant = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    # No link rows — user is in nothing.
    session = _StubSession(
        links={},
        tenants={other_tenant: _FakeTenantRow("hunter")},
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_tenant(
            request=_StubRequest(),
            x_tenant_id=other_tenant,
            user=user,
            db=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_current_tenant_returns_tenant_and_stamps_request_state() -> None:
    from rag.auth.tenant import get_current_tenant

    user = _FakeUser()
    tid = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    tenant = _FakeTenantRow("hunter")
    session = _StubSession(
        links={(tid, user.id): _FakeTenantUser("owner")},
        tenants={tid: tenant},
    )
    request = _StubRequest()

    out = await get_current_tenant(
        request=request,
        x_tenant_id=tid,
        user=user,
        db=session,
    )
    assert out is tenant
    assert request.state.tenant_id == tid
    assert request.state.tenant_slug == "hunter"
    assert request.state.tenant_role == "owner"


# --------------------------------------------------------------------------
# orchestrator._tenant_filter — must refuse to silently degrade
# --------------------------------------------------------------------------


def test_orchestrator_tenant_filter_raises_when_state_missing_tenant() -> None:
    from rag.orchestrator.nodes import _tenant_filter

    with pytest.raises(RuntimeError, match="tenant_id"):
        _tenant_filter({})

    with pytest.raises(RuntimeError, match="tenant_id"):
        _tenant_filter({"tenant_id": ""})


def test_orchestrator_tenant_filter_builds_qdrant_filter() -> None:
    from rag.orchestrator.nodes import _tenant_filter

    out = _tenant_filter({"tenant_id": "hunter"})
    assert isinstance(out, Filter)
    assert out.must is not None
    cond = out.must[0]
    assert isinstance(cond, FieldCondition)
    assert cond.key == "tenant_id"
    assert isinstance(cond.match, MatchValue)
    assert cond.match.value == "hunter"


# --------------------------------------------------------------------------
# Graph arm — _compose_filter always carries tenant predicate
# --------------------------------------------------------------------------


def test_graph_compose_filter_with_paths_and_tenant() -> None:
    from rag.retrieval.graph import _compose_filter

    f = _compose_filter(["a.md", "b.md"], tenant_id="hunter")
    assert isinstance(f, Filter)
    assert f.must is not None
    # First predicate is the tenant match.
    head = f.must[0]
    assert isinstance(head, FieldCondition)
    assert head.key == "tenant_id"
    assert head.match.value == "hunter"
    # Second predicate is the inner OR over file paths.
    inner = f.must[1]
    assert isinstance(inner, Filter)
    assert inner.should is not None and len(inner.should) == 2


def test_graph_compose_filter_tenant_only_when_no_paths() -> None:
    from rag.retrieval.graph import _compose_filter

    f = _compose_filter([], tenant_id="akiro")
    assert isinstance(f, Filter)
    assert f.must is not None and len(f.must) == 1
    head = f.must[0]
    assert isinstance(head, FieldCondition)
    assert head.key == "tenant_id"
    assert head.match.value == "akiro"


# --------------------------------------------------------------------------
# sparse._extract_tenant_slug
# --------------------------------------------------------------------------


def test_sparse_extract_tenant_slug_returns_value() -> None:
    from rag.retrieval.sparse import _extract_tenant_slug

    f = Filter(
        must=[
            FieldCondition(key="tenant_id", match=MatchValue(value="hunter")),
        ]
    )
    assert _extract_tenant_slug(f) == "hunter"


def test_sparse_extract_tenant_slug_returns_none_when_predicate_absent() -> None:
    from rag.retrieval.sparse import _extract_tenant_slug

    assert _extract_tenant_slug(None) is None
    f = Filter(must=[FieldCondition(key="file", match=MatchValue(value="x.md"))])
    assert _extract_tenant_slug(f) is None


# --------------------------------------------------------------------------
# Ingest payload carries tenant_id + point id is tenant-unique
# --------------------------------------------------------------------------


def test_chunks_from_file_stamps_tenant_id_and_uniques_ids(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Two different tenants ingesting the SAME file produce DIFFERENT
    point ids, so the int(uid,16)%2**63 reduction in upsert never collides
    and one tenant's chunks never silently overwrite the other's.
    """

    vault = tmp_path
    note = vault / "note.md"
    note.write_text("# heading\n\nbody text\n", encoding="utf-8")

    import ingest as ingest_module

    monkeypatch.setattr(ingest_module, "VAULT_PATH", vault)

    a = ingest_module.chunks_from_file(note, tenant_slug="hunter")
    b = ingest_module.chunks_from_file(note, tenant_slug="akiro")

    assert a, "expected at least one chunk for tenant hunter"
    assert b, "expected at least one chunk for tenant akiro"
    assert all(c["metadata"]["tenant_id"] == "hunter" for c in a)
    assert all(c["metadata"]["tenant_id"] == "akiro" for c in b)

    ids_a = {c["id"] for c in a}
    ids_b = {c["id"] for c in b}
    assert ids_a.isdisjoint(ids_b), (
        "tenant-unique point ids violated — cross-tenant overwrite possible"
    )
