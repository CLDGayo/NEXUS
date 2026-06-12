"""Phase 53 — WM-4 Usage Dashboard unit tests.

All tests are hermetic (no live Postgres, no live Qdrant).
DB session and Qdrant client are monkeypatched.

Coverage matrix
───────────────
 1. Member (non-manager) → 403
 2. Admin (manager) → 200 with correct shape
 3. document_count, product_count, member_count reflect DB counts
 4. Qdrant success → vector_chunks populated
 5. Qdrant failure → vector_chunks is None (graceful degrade, no 500)
 6. messages_total reflects DB count
 7. messages_7d series is zero-filled for all 7 days
 8. messages_7d aggregates counts from DB rows
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ── shared fixtures ──────────────────────────────────────────────────────────

TENANT_ID = uuid.UUID("6a30c6d2-2345-4def-9002-bbccddeeff00")
OWNER_ID = uuid.UUID("00000000-0000-0000-0002-000000000001")
ADMIN_ID = uuid.UUID("00000000-0000-0000-0002-000000000002")
MEMBER_ID = uuid.UUID("00000000-0000-0000-0002-000000000003")

TENANT_SLUG = "acme"


class _FakeTenant:
    def __init__(self) -> None:
        self.id = TENANT_ID
        self.name = "Acme"
        self.slug = TENANT_SLUG
        self.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)
        self.archived_at = None
        self.avatar_url = None


class _FakeUser:
    def __init__(self, user_id: uuid.UUID) -> None:
        self.id = user_id
        self.email = f"{user_id}@t.test"


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value

    def all(self) -> list[Any]:
        return []


class _ScalarResultWithRows:
    def __init__(self, value: int, rows: list[Any] | None = None) -> None:
        self._value = value
        self._rows = rows or []

    def scalar_one(self) -> int:
        return self._value

    def all(self) -> list[Any]:
        return self._rows


class _FakeDB:
    """Async stub for AsyncSession used in route handlers.

    ``counts`` is a list of int values returned sequentially for each
    ``execute()`` call (doc_count, product_count, member_count,
    messages_total, then 7d query).
    """

    def __init__(
        self,
        counts: list[int] | None = None,
        rows_7d: list[Any] | None = None,
    ) -> None:
        self._counts = list(counts or [0, 0, 0, 0])
        self._rows_7d = rows_7d or []
        self._call_index = 0

    async def get(self, model: Any, key: Any) -> Any:
        return None

    async def execute(self, _stmt: Any) -> Any:
        # The last execute call is the 7-day group-by query
        idx = self._call_index
        self._call_index += 1
        if idx < len(self._counts):
            return _ScalarResultWithRows(self._counts[idx])
        # 7-day rows query
        return _ScalarResultWithRows(0, self._rows_7d)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass


def _make_qdrant_ok(count: int = 42) -> AsyncMock:
    client = AsyncMock()
    result = MagicMock()
    result.count = count
    client.count = AsyncMock(return_value=result)
    return client


def _make_qdrant_fail() -> AsyncMock:
    client = AsyncMock()
    client.count = AsyncMock(side_effect=Exception("qdrant unavailable"))
    return client


# ── 1. Member → 403 via require_manager dep ──────────────────────────────────


@pytest.mark.asyncio
async def test_usage_member_403() -> None:
    """require_manager reads request.state.tenant_role and raises 403 for
    plain members. Verify the gate raises HTTPException 403 when the role
    is 'member'.
    """
    from types import SimpleNamespace

    from routers.deps import require_manager

    class _FakeRequest:
        state = SimpleNamespace(tenant_role="member")

    with pytest.raises(HTTPException) as exc_info:
        await require_manager(
            request=_FakeRequest(),  # type: ignore[arg-type]
            user=_FakeUser(MEMBER_ID),
            tenant=_FakeTenant(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "manager_role_required"


# ── 2. Admin → 200 with correct shape ────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_admin_200_shape() -> None:
    from routers.v2_tenants import TenantUsageRead, get_tenant_usage

    db = _FakeDB(counts=[5, 3, 4, 100])
    qdrant_client = _make_qdrant_ok(77)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert isinstance(result, TenantUsageRead)
    assert result.document_count == 5
    assert result.product_count == 3
    assert result.member_count == 4
    assert result.messages_total == 100
    assert result.vector_chunks == 77
    assert len(result.messages_7d) == 7


# ── 3. document_count, product_count, member_count reflect DB counts ─────────


@pytest.mark.asyncio
async def test_usage_counts_reflect_db() -> None:
    from routers.v2_tenants import get_tenant_usage

    db = _FakeDB(counts=[10, 20, 30, 0])
    qdrant_client = _make_qdrant_ok(0)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert result.document_count == 10
    assert result.product_count == 20
    assert result.member_count == 30


# ── 4. Qdrant success → vector_chunks populated ──────────────────────────────


@pytest.mark.asyncio
async def test_usage_qdrant_success_populates_vector_chunks() -> None:
    from routers.v2_tenants import get_tenant_usage

    db = _FakeDB(counts=[0, 0, 0, 0])
    qdrant_client = _make_qdrant_ok(999)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert result.vector_chunks == 999


# ── 5. Qdrant failure → vector_chunks is None ────────────────────────────────


@pytest.mark.asyncio
async def test_usage_qdrant_failure_degrades_gracefully() -> None:
    from routers.v2_tenants import get_tenant_usage

    db = _FakeDB(counts=[0, 0, 0, 0])
    qdrant_client = _make_qdrant_fail()

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert result.vector_chunks is None


# ── 6. messages_total reflects DB count ──────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_messages_total() -> None:
    from routers.v2_tenants import get_tenant_usage

    db = _FakeDB(counts=[0, 0, 0, 500])
    qdrant_client = _make_qdrant_ok(0)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert result.messages_total == 500


# ── 7. messages_7d series is zero-filled for all 7 days ──────────────────────


@pytest.mark.asyncio
async def test_usage_messages_7d_zero_filled() -> None:
    from routers.v2_tenants import get_tenant_usage

    db = _FakeDB(counts=[0, 0, 0, 0], rows_7d=[])
    qdrant_client = _make_qdrant_ok(0)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert len(result.messages_7d) == 7
    assert all(day.count == 0 for day in result.messages_7d)

    # Dates should be the last 7 days in ascending order
    today = datetime.now(timezone.utc).date()
    expected_dates = [
        (today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)
    ]
    actual_dates = [day.date for day in result.messages_7d]
    assert actual_dates == expected_dates


# ── 8. messages_7d aggregates counts from DB rows ────────────────────────────


@pytest.mark.asyncio
async def test_usage_messages_7d_aggregates_rows() -> None:
    from routers.v2_tenants import get_tenant_usage

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    # Simulate DB returning 2 rows: today=15, yesterday=7
    class _Row:
        def __init__(self, d: date, cnt: int) -> None:
            self.day = d
            self.cnt = cnt

    rows_7d = [_Row(today, 15), _Row(yesterday, 7)]
    db = _FakeDB(counts=[0, 0, 0, 22], rows_7d=rows_7d)
    qdrant_client = _make_qdrant_ok(0)

    with patch("routers.v2_tenants.get_qdrant_client", return_value=qdrant_client):
        result = await get_tenant_usage(
            tenant_id=TENANT_ID,
            tenant=_FakeTenant(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert len(result.messages_7d) == 7

    # Find today's and yesterday's entries
    day_map = {entry.date: entry.count for entry in result.messages_7d}
    assert day_map[today.isoformat()] == 15
    assert day_map[yesterday.isoformat()] == 7

    # All other days should be 0
    other_days = [
        d for d in day_map if d not in {today.isoformat(), yesterday.isoformat()}
    ]
    assert all(day_map[d] == 0 for d in other_days)
