"""Phase 56 — rotating refresh-token session layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from rag.auth.session import _sha256, issue_refresh_token, rotate_refresh_token


def _now():
    return datetime.now(timezone.utc)


def _db(row=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.unit
async def test_issue_refresh_token_stores_hash_only():
    db = _db()
    raw = await issue_refresh_token(db, uuid.uuid4())
    assert isinstance(raw, str) and len(raw) > 20
    db.add.assert_called_once()
    stored = db.add.call_args.args[0]
    assert stored.token_hash == _sha256(raw)
    assert stored.token_hash != raw  # never store the raw token
    db.flush.assert_awaited()


@pytest.mark.unit
async def test_rotate_valid_revokes_old_and_issues_new():
    uid = uuid.uuid4()
    row = SimpleNamespace(
        user_id=uid,
        revoked_at=None,
        expires_at=_now() + timedelta(days=1),
    )
    db = _db(row)
    result = await rotate_refresh_token(db, "raw-token")
    assert result is not None
    returned_uid, new_raw = result
    assert returned_uid == uid
    assert isinstance(new_raw, str)
    assert row.revoked_at is not None  # old token revoked on rotation
    db.add.assert_called_once()  # new token row


@pytest.mark.unit
async def test_rotate_revoked_token_rejected():
    row = SimpleNamespace(
        user_id=uuid.uuid4(),
        revoked_at=_now(),
        expires_at=_now() + timedelta(days=1),
    )
    assert await rotate_refresh_token(_db(row), "raw") is None


@pytest.mark.unit
async def test_rotate_expired_token_rejected():
    row = SimpleNamespace(
        user_id=uuid.uuid4(),
        revoked_at=None,
        expires_at=_now() - timedelta(days=1),
    )
    assert await rotate_refresh_token(_db(row), "raw") is None


@pytest.mark.unit
async def test_rotate_unknown_token_rejected():
    assert await rotate_refresh_token(_db(None), "raw") is None
