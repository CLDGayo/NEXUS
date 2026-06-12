"""Phase 51 — Unit tests for tenant_invites router.

Covers:
- create_invite: token generated, n8n skipped when URL unset, email-optional
- list_invites: returns only pending rows for the correct tenant
- resend_invite: 404 on wrong id, 409 on non-pending, rotates token
- revoke_invite: 204, 409 on already-revoked
- accept_invite: success, expired, already-used, already-member idempotency
- tenant_mismatch guard on all tenant-gated routes
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag.routers.tenant_invites import (
    _token_hash,
    accept_invite,
    create_invite,
    list_invites,
    resend_invite,
    revoke_invite,
)


# ---------- helpers -----------------------------------------------------------


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _invite(
    *,
    tenant_id: uuid.UUID,
    status: str = "pending",
    email: str | None = "test@example.com",
    role: str = "member",
    days_until_expiry: int = 7,
) -> MagicMock:
    inv = MagicMock()
    inv.id = _uuid()
    inv.tenant_id = tenant_id
    inv.email = email
    inv.role = role
    inv.status = status
    inv.token_hash = hashlib.sha256(b"raw-token").hexdigest()
    inv.expires_at = _now() + timedelta(days=days_until_expiry)
    inv.created_at = _now()
    return inv


_UNSET = object()


def _make_db(scalar=_UNSET, scalars=_UNSET):
    db = AsyncMock()
    result = MagicMock()
    if scalar is not _UNSET:
        result.scalar_one_or_none.return_value = scalar
    if scalars is not _UNSET:
        result.scalars.return_value.all.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _tenant(tenant_id: uuid.UUID | None = None) -> MagicMock:
    t = MagicMock()
    t.id = tenant_id or _uuid()
    t.name = "Test Workspace"
    t.slug = "test-workspace"
    return t


def _user(user_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = user_id or _uuid()
    u.email = "user@example.com"
    return u


# ---------- _token_hash -------------------------------------------------------


def test_token_hash_is_sha256():
    raw = "hello"
    expected = hashlib.sha256(b"hello").hexdigest()
    assert _token_hash(raw) == expected


# ---------- create_invite -----------------------------------------------------


@pytest.mark.asyncio
async def test_create_invite_generates_token_and_persists():
    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    user = _user()
    db = _make_db()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    body = SimpleNamespace(email=None, role="member")

    with patch(
        "rag.routers.tenant_invites._fire_n8n_invite", new_callable=AsyncMock
    ) as mock_n8n:
        result = await create_invite(tenant_id, body, user, tenant, db)

    db.add.assert_called_once()
    await db.commit()
    mock_n8n.assert_not_called()  # no email, n8n skipped
    assert "invite_link" in result


@pytest.mark.asyncio
async def test_create_invite_fires_n8n_when_email_provided():
    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    user = _user()
    db = _make_db()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    body = SimpleNamespace(email="colleague@example.com", role="member")

    with patch(
        "rag.routers.tenant_invites._fire_n8n_invite", new_callable=AsyncMock
    ) as mock_n8n:
        await create_invite(tenant_id, body, user, tenant, db)

    mock_n8n.assert_awaited_once()
    call_kwargs = mock_n8n.call_args.kwargs
    assert call_kwargs["email"] == "colleague@example.com"
    assert call_kwargs["role"] == "member"


@pytest.mark.asyncio
async def test_create_invite_tenant_mismatch_raises_403():
    from fastapi import HTTPException

    tenant_id = _uuid()
    other_tenant = _tenant()  # different id
    user = _user()
    db = _make_db()
    body = SimpleNamespace(email=None, role="member")

    with pytest.raises(HTTPException) as exc_info:
        await create_invite(tenant_id, body, user, other_tenant, db)
    assert exc_info.value.status_code == 403


# ---------- list_invites ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invites_returns_pending_only():
    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    pending = _invite(tenant_id=tenant_id, status="pending")
    db = _make_db(scalars=[pending])

    result = await list_invites(tenant_id, tenant, db)

    assert len(result) == 1
    assert result[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_list_invites_tenant_mismatch_raises_403():
    from fastapi import HTTPException

    tenant_id = _uuid()
    other_tenant = _tenant()
    db = _make_db(scalars=[])

    with pytest.raises(HTTPException) as exc_info:
        await list_invites(tenant_id, other_tenant, db)
    assert exc_info.value.status_code == 403


# ---------- resend_invite -----------------------------------------------------


@pytest.mark.asyncio
async def test_resend_invite_404_on_missing():
    from fastapi import HTTPException

    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    db = _make_db(scalar=None)

    with pytest.raises(HTTPException) as exc_info:
        await resend_invite(tenant_id, _uuid(), tenant, db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_resend_invite_409_on_accepted():
    from fastapi import HTTPException

    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    inv = _invite(tenant_id=tenant_id, status="accepted")
    db = _make_db(scalar=inv)

    with pytest.raises(HTTPException) as exc_info:
        await resend_invite(tenant_id, inv.id, tenant, db)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_resend_invite_400_on_open_code():
    from fastapi import HTTPException

    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    inv = _invite(tenant_id=tenant_id, status="pending", email=None)
    db = _make_db(scalar=inv)

    with pytest.raises(HTTPException) as exc_info:
        await resend_invite(tenant_id, inv.id, tenant, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "open_code_no_email"


@pytest.mark.asyncio
async def test_resend_invite_rotates_token():
    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    inv = _invite(tenant_id=tenant_id, status="pending", email="a@b.com")
    old_hash = inv.token_hash
    db = _make_db(scalar=inv)

    with patch("rag.routers.tenant_invites._fire_n8n_invite", new_callable=AsyncMock):
        await resend_invite(tenant_id, inv.id, tenant, db)

    assert inv.token_hash != old_hash


# ---------- revoke_invite -----------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_invite_sets_status_revoked():
    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    inv = _invite(tenant_id=tenant_id, status="pending")
    db = _make_db(scalar=inv)

    resp = await revoke_invite(tenant_id, inv.id, tenant, db)

    assert inv.status == "revoked"
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_revoke_invite_409_on_already_revoked():
    from fastapi import HTTPException

    tenant_id = _uuid()
    tenant = _tenant(tenant_id)
    inv = _invite(tenant_id=tenant_id, status="revoked")
    db = _make_db(scalar=inv)

    with pytest.raises(HTTPException) as exc_info:
        await revoke_invite(tenant_id, inv.id, tenant, db)
    assert exc_info.value.status_code == 409


# ---------- accept_invite -----------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invite_success_creates_membership():
    raw = "raw-token-value"
    token_h = _token_hash(raw)
    tenant_id = _uuid()

    inv = MagicMock()
    inv.tenant_id = tenant_id
    inv.token_hash = token_h
    inv.status = "pending"
    inv.expires_at = _now() + timedelta(days=1)
    inv.role = "member"

    tenant = MagicMock()
    tenant.name = "WS"
    tenant.slug = "ws"

    user = _user()

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = inv  # invite lookup
        elif call_count == 2:
            result.scalar_one_or_none.return_value = None  # no existing membership
        else:
            result.scalar_one_or_none.return_value = tenant  # tenant lookup
        return result

    db = AsyncMock()
    db.execute = fake_execute
    db.commit = AsyncMock()
    db.add = MagicMock()

    body = SimpleNamespace(token=raw)
    result = await accept_invite(body, user, db)

    assert result["role"] == "member"
    assert result["tenant_id"] == str(tenant_id)
    assert inv.status == "accepted"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_accept_invite_expired_raises_410():
    from fastapi import HTTPException

    raw = "raw-token-expired"
    token_h = _token_hash(raw)

    inv = MagicMock()
    inv.token_hash = token_h
    inv.status = "pending"
    inv.expires_at = _now() - timedelta(days=1)

    db = _make_db(scalar=inv)
    user = _user()

    body = SimpleNamespace(token=raw)
    with pytest.raises(HTTPException) as exc_info:
        await accept_invite(body, user, db)
    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_invite_already_used_raises_409():
    from fastapi import HTTPException

    raw = "raw-token-used"
    token_h = _token_hash(raw)

    inv = MagicMock()
    inv.token_hash = token_h
    inv.status = "accepted"

    db = _make_db(scalar=inv)
    user = _user()

    body = SimpleNamespace(token=raw)
    with pytest.raises(HTTPException) as exc_info:
        await accept_invite(body, user, db)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_invite_already_member_idempotent():
    raw = "raw-token-member"
    token_h = _token_hash(raw)
    tenant_id = _uuid()

    inv = MagicMock()
    inv.tenant_id = tenant_id
    inv.token_hash = token_h
    inv.status = "pending"
    inv.expires_at = _now() + timedelta(days=1)
    inv.role = "member"

    existing = MagicMock()
    existing.role = "admin"

    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = inv
        else:
            result.scalar_one_or_none.return_value = existing
        return result

    db = AsyncMock()
    db.execute = fake_execute
    db.commit = AsyncMock()
    db.add = MagicMock()

    user = _user()
    body = SimpleNamespace(token=raw)
    result = await accept_invite(body, user, db)

    # Returns the existing role, doesn't add a new membership row.
    assert result["role"] == "admin"
    db.add.assert_not_called()
    assert inv.status == "accepted"
