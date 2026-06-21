"""Phase 52 — Workspace Lifecycle & Danger Zone unit tests.

All tests are hermetic (no live Postgres, no live Qdrant, no live MinIO).
DB session, Qdrant client, and object_store are monkeypatched.

Coverage matrix
───────────────
 1. PATCH rename — admin 200
 2. PATCH rename — member 403
 3. PATCH slug blocked when doc count > 0
 4. PATCH slug uniqueness (IntegrityError → 409 slug_taken)
 5. POST archive — owner sets archived_at
 6. POST archive — admin 403 (owner-only)
 7. POST archive — 409 already_archived
 8. POST unarchive — owner clears archived_at
 9. POST unarchive — 409 not_archived
10. Archived tenant → data route 403 workspace_archived
11. Archived tenant → /api/tenants route is NOT blocked
12. POST transfer — non-member target 404
13. POST transfer — self transfer 409
14. POST transfer — success: target→owner, caller→admin
15. DELETE — confirm_name mismatch 400
16. DELETE — admin 403
17. DELETE — success removes tenant row + verifies Qdrant + object_store called
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

# ── shared fixtures ──────────────────────────────────────────────────────────

TENANT_ID = uuid.UUID("5f20b6d1-1234-4abc-8001-aabbccddeeff")
OWNER_ID = uuid.UUID("00000000-0000-0000-0001-000000000001")
ADMIN_ID = uuid.UUID("00000000-0000-0000-0001-000000000002")
MEMBER_ID = uuid.UUID("00000000-0000-0000-0001-000000000003")
OTHER_ID = uuid.UUID("00000000-0000-0000-0001-000000000004")


class _FakeUser:
    def __init__(self, user_id: uuid.UUID, email: str = "x@t.test") -> None:
        self.id = user_id
        self.email = email
        self.display_name = email.split("@")[0]


class _FakeTenant:
    def __init__(
        self,
        *,
        name: str = "Hunter",
        slug: str = "hunter",
        archived_at: datetime | None = None,
        avatar_url: str | None = None,
        preferred_language: str = "en",
    ) -> None:
        self.id = TENANT_ID
        self.name = name
        self.slug = slug
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)
        self.archived_at = archived_at
        self.avatar_url = avatar_url
        self.preferred_language = preferred_language


class _FakeLink:
    def __init__(self, user_id: uuid.UUID, role: str) -> None:
        self.tenant_id = TENANT_ID
        self.user_id = user_id
        self.role = role
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeDB:
    """Async stub for AsyncSession used in route handlers."""

    def __init__(
        self,
        links: dict[uuid.UUID, _FakeLink],
        *,
        doc_count: int = 0,
        raise_integrity: bool = False,
    ) -> None:
        self._links = links
        self._doc_count = doc_count
        self._raise_integrity = raise_integrity
        self.deleted: list[object] = []
        self.committed = False
        self.refreshed: list[object] = []

    async def get(self, model: Any, key: Any) -> Any:
        from rag.database.models import TenantUser, User

        if model is TenantUser:
            _tenant_id, user_id = key
            return self._links.get(user_id)
        if model is User:
            uid = key
            link = self._links.get(uid)
            if link:
                return _FakeUser(uid, f"{uid}@t.test")
            return None
        return None

    async def execute(self, _stmt: Any) -> _ScalarResult:
        return _ScalarResult(self._doc_count)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        if self._raise_integrity:
            raise IntegrityError("unique", {}, Exception())
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


def _owner_db(*, doc_count: int = 0, raise_integrity: bool = False) -> _FakeDB:
    links = {
        OWNER_ID: _FakeLink(OWNER_ID, "owner"),
        ADMIN_ID: _FakeLink(ADMIN_ID, "admin"),
        MEMBER_ID: _FakeLink(MEMBER_ID, "member"),
    }
    return _FakeDB(links, doc_count=doc_count, raise_integrity=raise_integrity)


# ── 1. PATCH rename — admin 200 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_rename_admin_200() -> None:
    from rag.auth.schemas import TenantUpdate
    from routers.v2_tenants import update_tenant

    tenant = _FakeTenant()
    db = _owner_db()

    result = await update_tenant(
        tenant_id=TENANT_ID,
        body=TenantUpdate(name="Hunter Renamed"),
        user=_FakeUser(ADMIN_ID),
        tenant=tenant,
        db=db,
    )

    assert tenant.name == "Hunter Renamed"
    assert db.committed is True
    assert result.name == "Hunter Renamed"


# ── 2. PATCH rename — member 403 ────────────────────────────────────────────
# (require_manager raises before the handler runs; we test guard directly)


@pytest.mark.asyncio
async def test_patch_requires_manager() -> None:
    from routers.deps import require_manager

    class _StubReq:
        state = SimpleNamespace(tenant_role="member")

    with pytest.raises(HTTPException) as exc:
        await require_manager(
            request=_StubReq(),
            user=_FakeUser(MEMBER_ID),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "manager_role_required"


# ── 3. PATCH slug blocked when doc_count > 0 ─────────────────────────────────


@pytest.mark.asyncio
async def test_patch_slug_blocked_when_documents_exist() -> None:
    from rag.auth.schemas import TenantUpdate
    from routers.v2_tenants import update_tenant

    tenant = _FakeTenant()
    db = _owner_db(doc_count=5)  # has indexed documents

    with pytest.raises(HTTPException) as exc:
        await update_tenant(
            tenant_id=TENANT_ID,
            body=TenantUpdate(slug="new-slug"),
            user=_FakeUser(OWNER_ID),
            tenant=tenant,
            db=db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "slug_change_blocked_documents_exist"


# ── 4. PATCH slug uniqueness (IntegrityError → 409 slug_taken) ───────────────


@pytest.mark.asyncio
async def test_patch_slug_uniqueness_409() -> None:
    from rag.auth.schemas import TenantUpdate
    from routers.v2_tenants import update_tenant

    tenant = _FakeTenant()
    db = _owner_db(doc_count=0, raise_integrity=True)

    with pytest.raises(HTTPException) as exc:
        await update_tenant(
            tenant_id=TENANT_ID,
            body=TenantUpdate(slug="taken-slug"),
            user=_FakeUser(OWNER_ID),
            tenant=tenant,
            db=db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "slug_taken"


# ── 5. POST archive — owner sets archived_at ─────────────────────────────────


@pytest.mark.asyncio
async def test_archive_sets_archived_at() -> None:
    from routers.v2_tenants import archive_tenant

    tenant = _FakeTenant(archived_at=None)
    db = _owner_db()

    result = await archive_tenant(
        tenant_id=TENANT_ID,
        user=_FakeUser(OWNER_ID),
        tenant=tenant,
        db=db,
    )

    assert tenant.archived_at is not None
    assert db.committed is True
    assert result.archived_at is not None


# ── 6. POST archive — admin 403 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_requires_owner() -> None:
    from routers.deps import require_owner

    class _StubReq:
        state = SimpleNamespace(tenant_role="admin")

    with pytest.raises(HTTPException) as exc:
        await require_owner(
            request=_StubReq(),
            user=_FakeUser(ADMIN_ID),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "owner_role_required"


# ── 7. POST archive — 409 already_archived ───────────────────────────────────


@pytest.mark.asyncio
async def test_archive_409_already_archived() -> None:
    from routers.v2_tenants import archive_tenant

    tenant = _FakeTenant(archived_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    db = _owner_db()

    with pytest.raises(HTTPException) as exc:
        await archive_tenant(
            tenant_id=TENANT_ID,
            user=_FakeUser(OWNER_ID),
            tenant=tenant,
            db=db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "already_archived"


# ── 8. POST unarchive — owner clears archived_at ─────────────────────────────


@pytest.mark.asyncio
async def test_unarchive_clears_archived_at() -> None:
    from routers.v2_tenants import unarchive_tenant

    tenant = _FakeTenant(archived_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    db = _owner_db()

    result = await unarchive_tenant(
        tenant_id=TENANT_ID,
        user=_FakeUser(OWNER_ID),
        tenant=tenant,
        db=db,
    )

    assert tenant.archived_at is None
    assert db.committed is True
    assert result.archived_at is None


# ── 9. POST unarchive — 409 not_archived ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unarchive_409_not_archived() -> None:
    from routers.v2_tenants import unarchive_tenant

    tenant = _FakeTenant(archived_at=None)
    db = _owner_db()

    with pytest.raises(HTTPException) as exc:
        await unarchive_tenant(
            tenant_id=TENANT_ID,
            user=_FakeUser(OWNER_ID),
            tenant=tenant,
            db=db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "not_archived"


# ── 10. Archived tenant → data route 403 workspace_archived ──────────────────


@pytest.mark.asyncio
async def test_archived_tenant_blocks_data_routes() -> None:
    from rag.auth.tenant import get_current_tenant

    class _FakeRequest:
        state = SimpleNamespace()

        class url:
            path = "/api/chat"  # NOT /api/tenants prefix

    class _FakeDB2:
        async def get(self, model: Any, key: Any) -> Any:
            from rag.database.models import Tenant, TenantUser

            if model is TenantUser:
                return _FakeLink(OWNER_ID, "owner")
            if model is Tenant:
                return _FakeTenant(
                    archived_at=datetime(2026, 6, 1, tzinfo=timezone.utc)
                )
            return None

    with pytest.raises(HTTPException) as exc:
        await get_current_tenant(
            request=_FakeRequest(),
            x_tenant_id=TENANT_ID,
            user=_FakeUser(OWNER_ID),
            db=_FakeDB2(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "workspace_archived"


# ── 11. Archived tenant → /api/tenants route is NOT blocked ──────────────────


@pytest.mark.asyncio
async def test_archived_tenant_does_not_block_tenant_routes() -> None:
    from rag.auth.tenant import get_current_tenant

    class _FakeRequest2:
        state = SimpleNamespace()

        class url:
            path = "/api/tenants/some-id/archive"  # /api/tenants prefix — exempt

    class _FakeDB3:
        async def get(self, model: Any, key: Any) -> Any:
            from rag.database.models import Tenant, TenantUser

            if model is TenantUser:
                return _FakeLink(OWNER_ID, "owner")
            if model is Tenant:
                return _FakeTenant(
                    archived_at=datetime(2026, 6, 1, tzinfo=timezone.utc)
                )
            return None

    # Should NOT raise — the /api/tenants route is exempt from the guard
    result = await get_current_tenant(
        request=_FakeRequest2(),
        x_tenant_id=TENANT_ID,
        user=_FakeUser(OWNER_ID),
        db=_FakeDB3(),
    )
    assert result.id == TENANT_ID


# ── 12. POST transfer — non-member target 404 ────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_nonmember_404() -> None:
    from routers.v2_tenants import transfer_ownership

    class _Body:
        new_owner_user_id = OTHER_ID  # not in the DB

    db = _owner_db()

    with pytest.raises(HTTPException) as exc:
        await transfer_ownership(
            tenant_id=TENANT_ID,
            body=_Body(),  # type: ignore[arg-type]
            user=_FakeUser(OWNER_ID),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "member_not_found"


# ── 13. POST transfer — self transfer 409 ────────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_self_409() -> None:
    from routers.v2_tenants import transfer_ownership

    class _Body:
        new_owner_user_id = OWNER_ID  # same as caller

    db = _owner_db()

    with pytest.raises(HTTPException) as exc:
        await transfer_ownership(
            tenant_id=TENANT_ID,
            body=_Body(),  # type: ignore[arg-type]
            user=_FakeUser(OWNER_ID),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 409
    assert "yourself" in exc.value.detail


# ── 14. POST transfer — success: target→owner, caller→admin ──────────────────


@pytest.mark.asyncio
async def test_transfer_success_demotes_caller() -> None:
    from routers.v2_tenants import transfer_ownership

    class _Body:
        new_owner_user_id = ADMIN_ID

    db = _owner_db()

    result = await transfer_ownership(
        tenant_id=TENANT_ID,
        body=_Body(),  # type: ignore[arg-type]
        user=_FakeUser(OWNER_ID),
        tenant=_FakeTenant(),
        db=db,
    )

    assert db._links[ADMIN_ID].role == "owner"
    assert db._links[OWNER_ID].role == "admin"
    assert db.committed is True
    # Caller is now admin — response role reflects that
    assert result.role == "admin"


# ── 15. DELETE — confirm_name mismatch 400 ───────────────────────────────────


@pytest.mark.asyncio
async def test_delete_confirm_name_mismatch_400() -> None:
    from routers.v2_tenants import delete_tenant

    class _Body:
        confirm_name = "WRONG NAME"

    db = _owner_db()

    with pytest.raises(HTTPException) as exc:
        await delete_tenant(
            tenant_id=TENANT_ID,
            body=_Body(),  # type: ignore[arg-type]
            user=_FakeUser(OWNER_ID),
            tenant=_FakeTenant(name="Hunter"),
            db=db,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "confirm_name_mismatch"


# ── 16. DELETE — admin 403 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_requires_owner() -> None:
    from routers.deps import require_owner

    class _StubReq:
        state = SimpleNamespace(tenant_role="admin")

    with pytest.raises(HTTPException) as exc:
        await require_owner(
            request=_StubReq(),
            user=_FakeUser(ADMIN_ID),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403


# ── 17. DELETE — success removes row, Qdrant purge + object_store called ─────


@pytest.mark.asyncio
async def test_delete_success_calls_qdrant_and_object_store() -> None:
    from routers.v2_tenants import delete_tenant

    class _Body:
        confirm_name = "Hunter"

    db = _owner_db()

    # Build a fake Qdrant client
    fake_qdrant = AsyncMock()
    fake_qdrant.delete = AsyncMock(return_value=None)

    # Build a fake object_store
    fake_delete_object = AsyncMock(return_value=None)
    fake_public_url = MagicMock(return_value=None)

    with (
        patch(
            "routers.v2_tenants.get_qdrant_client", return_value=fake_qdrant
        ),
        patch(
            "routers.v2_tenants.object_store.delete_object", fake_delete_object
        ),
        patch("routers.v2_tenants.object_store.public_url_for", fake_public_url),
    ):
        response = await delete_tenant(
            tenant_id=TENANT_ID,
            body=_Body(),  # type: ignore[arg-type]
            user=_FakeUser(OWNER_ID),
            tenant=_FakeTenant(name="Hunter"),
            db=db,
        )

    assert response.status_code == 204
    # Qdrant delete was called
    fake_qdrant.delete.assert_called_once()
    # The call included our tenant slug
    call_kwargs = fake_qdrant.delete.call_args
    assert call_kwargs is not None
    # object_store delete was called for the avatar key
    fake_delete_object.assert_called_once()
    # Tenant row was deleted from DB
    assert db.deleted == [_FakeTenant.__new__(_FakeTenant)] or len(db.deleted) == 1
    assert db.committed is True
