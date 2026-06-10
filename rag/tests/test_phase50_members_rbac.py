"""Phase 50 — require_manager dependency + member-management RBAC guards.

Unit-scoped (no Postgres): handlers are called directly with a fake
AsyncSession that serves canned ``TenantUser`` / ``User`` rows. The guard
matrix under test:

    * ``require_manager`` — owner and admin pass, member and unset 403.
    * ``update_member_role`` — admins cannot touch owners nor grant the
      owner role; the last owner can never be demoted.
    * ``remove_member`` — admins cannot remove owners; the last owner can
      never be removed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

TENANT_ID = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
OWNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
MEMBER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


class _FakeUser:
    def __init__(self, user_id: uuid.UUID, email: str) -> None:
        self.id = user_id
        self.email = email
        self.display_name = email.split("@")[0]


class _FakeTenant:
    def __init__(self) -> None:
        self.id = TENANT_ID
        self.name = "Hunter"
        self.slug = "cozy-downloads-store"
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


class _FakeLink:
    def __init__(self, user_id: uuid.UUID, role: str) -> None:
        self.tenant_id = TENANT_ID
        self.user_id = user_id
        self.role = role
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


class _StubRequest:
    def __init__(self, role: str | None) -> None:
        self.state = type("S", (), {"tenant_role": role})()


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeDB:
    """Serves TenantUser/User rows from dicts; counts owners from the rows."""

    def __init__(
        self,
        links: dict[uuid.UUID, _FakeLink],
        users: dict[uuid.UUID, _FakeUser],
    ) -> None:
        self._links = links
        self._users = users
        self.deleted: list[object] = []
        self.committed = False

    async def get(self, model, key):  # noqa: ANN001 — mirrors AsyncSession.get
        from rag.database.models import TenantUser, User

        if model is TenantUser:
            _tenant_id, user_id = key
            return self._links.get(user_id)
        if model is User:
            return self._users.get(key)
        return None

    async def execute(self, stmt):  # noqa: ANN001 — only the owner count query
        owners = sum(1 for link in self._links.values() if link.role == "owner")
        return _ScalarResult(owners)

    async def delete(self, obj) -> None:  # noqa: ANN001
        self.deleted.append(obj)
        for user_id, link in list(self._links.items()):
            if link is obj:
                del self._links[user_id]

    async def commit(self) -> None:
        self.committed = True


def _three_member_db() -> _FakeDB:
    links = {
        OWNER_ID: _FakeLink(OWNER_ID, "owner"),
        ADMIN_ID: _FakeLink(ADMIN_ID, "admin"),
        MEMBER_ID: _FakeLink(MEMBER_ID, "member"),
    }
    users = {
        OWNER_ID: _FakeUser(OWNER_ID, "owner@nexus.test"),
        ADMIN_ID: _FakeUser(ADMIN_ID, "admin@nexus.test"),
        MEMBER_ID: _FakeUser(MEMBER_ID, "member@nexus.test"),
    }
    return _FakeDB(links, users)


# --------------------------------------------------------------------------
# require_manager
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_require_manager_passes_for_manager_roles(role: str) -> None:
    from routers.deps import require_manager

    tenant = _FakeTenant()
    out = await require_manager(
        request=_StubRequest(role),
        user=_FakeUser(OWNER_ID, "x@nexus.test"),
        tenant=tenant,
    )
    assert out is tenant


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", None, "superadmin"])
async def test_require_manager_403s_for_non_manager(role: str | None) -> None:
    from routers.deps import require_manager

    with pytest.raises(HTTPException) as exc:
        await require_manager(
            request=_StubRequest(role),
            user=_FakeUser(MEMBER_ID, "x@nexus.test"),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "manager_role_required"


# --------------------------------------------------------------------------
# update_member_role guards
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_modify_owner() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            tenant_id=TENANT_ID,
            member_user_id=OWNER_ID,
            body=MemberRoleUpdate(role="member"),
            user=_FakeUser(ADMIN_ID, "admin@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 403
    assert "admins cannot modify owners" in exc.value.detail


@pytest.mark.asyncio
async def test_admin_cannot_grant_owner_role() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            tenant_id=TENANT_ID,
            member_user_id=MEMBER_ID,
            body=MemberRoleUpdate(role="owner"),
            user=_FakeUser(ADMIN_ID, "admin@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 403
    assert "only owners can grant" in exc.value.detail


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()  # exactly one owner
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            tenant_id=TENANT_ID,
            member_user_id=OWNER_ID,
            body=MemberRoleUpdate(role="admin"),
            user=_FakeUser(OWNER_ID, "owner@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 409
    assert "last owner" in exc.value.detail


@pytest.mark.asyncio
async def test_owner_promotes_member_to_admin() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    out = await update_member_role(
        tenant_id=TENANT_ID,
        member_user_id=MEMBER_ID,
        body=MemberRoleUpdate(role="admin"),
        user=_FakeUser(OWNER_ID, "owner@nexus.test"),
        tenant=_FakeTenant(),
        db=db,
    )
    assert out.role == "admin"
    assert db.committed is True


@pytest.mark.asyncio
async def test_update_unknown_member_404s() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            tenant_id=TENANT_ID,
            member_user_id=uuid.uuid4(),
            body=MemberRoleUpdate(role="admin"),
            user=_FakeUser(OWNER_ID, "owner@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_path_header_mismatch_rejected() -> None:
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    with pytest.raises(HTTPException) as exc:
        await update_member_role(
            tenant_id=uuid.uuid4(),  # disagrees with tenant.id from header
            member_user_id=MEMBER_ID,
            body=MemberRoleUpdate(role="admin"),
            user=_FakeUser(OWNER_ID, "owner@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------
# remove_member guards
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_remove_owner() -> None:
    from routers.v2_tenants import remove_member

    db = _three_member_db()
    with pytest.raises(HTTPException) as exc:
        await remove_member(
            tenant_id=TENANT_ID,
            member_user_id=OWNER_ID,
            user=_FakeUser(ADMIN_ID, "admin@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 403
    assert "admins cannot remove owners" in exc.value.detail


@pytest.mark.asyncio
async def test_last_owner_cannot_be_removed() -> None:
    from routers.v2_tenants import remove_member

    db = _three_member_db()  # exactly one owner — even self-removal blocked
    with pytest.raises(HTTPException) as exc:
        await remove_member(
            tenant_id=TENANT_ID,
            member_user_id=OWNER_ID,
            user=_FakeUser(OWNER_ID, "owner@nexus.test"),
            tenant=_FakeTenant(),
            db=db,
        )
    assert exc.value.status_code == 409
    assert "last owner" in exc.value.detail


@pytest.mark.asyncio
async def test_admin_removes_member() -> None:
    from routers.v2_tenants import remove_member

    db = _three_member_db()
    await remove_member(
        tenant_id=TENANT_ID,
        member_user_id=MEMBER_ID,
        user=_FakeUser(ADMIN_ID, "admin@nexus.test"),
        tenant=_FakeTenant(),
        db=db,
    )
    assert db.committed is True
    assert MEMBER_ID not in db._links


@pytest.mark.asyncio
async def test_second_owner_can_be_demoted() -> None:
    """With two owners the demotion guard does not fire."""
    from rag.auth.schemas import MemberRoleUpdate
    from routers.v2_tenants import update_member_role

    db = _three_member_db()
    db._links[ADMIN_ID].role = "owner"  # now two owners
    out = await update_member_role(
        tenant_id=TENANT_ID,
        member_user_id=ADMIN_ID,
        body=MemberRoleUpdate(role="admin"),
        user=_FakeUser(OWNER_ID, "owner@nexus.test"),
        tenant=_FakeTenant(),
        db=db,
    )
    assert out.role == "admin"
