"""Phase 31 — require_owner dependency rejects non-owner roles."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _FakeTenant:
    def __init__(self) -> None:
        self.id = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
        self.name = "Hunter"
        self.slug = "cozy-downloads-store"
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)


class _StubRequest:
    def __init__(self, role: str | None) -> None:
        self.state = type("S", (), {"tenant_role": role})()


@pytest.mark.asyncio
async def test_require_owner_passes_for_owner_role() -> None:
    from routers.deps import require_owner

    tenant = _FakeTenant()
    out = await require_owner(
        request=_StubRequest("owner"),
        user=_FakeUser(),
        tenant=tenant,
    )
    assert out is tenant


@pytest.mark.asyncio
async def test_require_owner_403s_for_member_role() -> None:
    from routers.deps import require_owner

    with pytest.raises(HTTPException) as exc:
        await require_owner(
            request=_StubRequest("member"),
            user=_FakeUser(),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "owner_role_required"


@pytest.mark.asyncio
async def test_require_owner_403s_when_role_unset() -> None:
    from routers.deps import require_owner

    with pytest.raises(HTTPException) as exc:
        await require_owner(
            request=_StubRequest(None),
            user=_FakeUser(),
            tenant=_FakeTenant(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "owner_role_required"
