"""Phase 32.2 — `_resolve_session` lazy-creates on a fresh client UUID.

The pre-32.2 behavior raised ``404 session not found`` on any FE-provided
UUID with no backing row, which is exactly the lifecycle the SPA uses
(``crypto.randomUUID()`` minted client-side). The lazy-create path makes
the first turn succeed and persist a row.

This file pairs an async behavioral test (mocked ``AsyncSession``) with
source-grep guards that fail loudly if a future PR re-introduces the
strict 404 branch or drops the ``IntegrityError`` race handling.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from routers import chat as chat_module


class _FakeSession:
    """Just enough of ``AsyncSession`` to drive ``_resolve_session``."""

    def __init__(self, *, existing: Any | None = None, integrity_on_commit: bool = False) -> None:
        self.existing = existing
        self.added: list[Any] = []
        self.committed = 0
        self.rolled_back = 0
        self.refreshed: list[Any] = []
        self._integrity_armed = integrity_on_commit
        self._second_get_returns = existing

    async def get(self, _model: type, _pk: Any) -> Any | None:
        return self.existing if self.existing is not None else self._second_get_returns

    def add(self, row: Any) -> None:
        self.added.append(row)
        # The row becomes the next "existing" so the re-read after a race
        # finds the winning insert.
        self._second_get_returns = row

    async def commit(self) -> None:
        if self._integrity_armed:
            self._integrity_armed = False
            raise IntegrityError("dup", {}, Exception("duplicate key"))
        self.committed += 1
        # First commit publishes the staged row as the "live" one.
        if self.added and self.existing is None:
            self.existing = self.added[-1]

    async def rollback(self) -> None:
        self.rolled_back += 1
        # After rollback the FakeSession behaves as if the conflicting
        # row already exists (a sibling caller won the race).
        if self.added:
            self.existing = self.added[-1]

    async def refresh(self, _row: Any, attribute_names: list[str] | None = None) -> None:
        self.refreshed.append(_row)


@pytest.mark.asyncio
async def test_resolve_session_lazy_creates_on_unknown_uuid() -> None:
    db = _FakeSession()
    user = SimpleNamespace(id=uuid.uuid4())
    tenant = SimpleNamespace(id=uuid.uuid4())
    sid = str(uuid.uuid4())

    out = await chat_module._resolve_session(db, user, tenant, sid)

    assert out == sid
    assert len(db.added) == 1
    inserted = db.added[0]
    assert inserted.session_id == sid
    assert inserted.user_id == user.id
    assert inserted.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_resolve_session_returns_existing_row_unchanged_owner() -> None:
    user = SimpleNamespace(id=uuid.uuid4())
    tenant = SimpleNamespace(id=uuid.uuid4())
    sid = str(uuid.uuid4())
    existing = SimpleNamespace(
        session_id=sid, user_id=user.id, tenant_id=tenant.id, title=None
    )
    db = _FakeSession(existing=existing)

    out = await chat_module._resolve_session(db, user, tenant, sid)
    assert out == sid
    assert len(db.added) == 0  # no insert — row already there


@pytest.mark.asyncio
async def test_resolve_session_rejects_wrong_tenant() -> None:
    user = SimpleNamespace(id=uuid.uuid4())
    tenant = SimpleNamespace(id=uuid.uuid4())
    sid = str(uuid.uuid4())
    other_tenant_id = uuid.uuid4()
    existing = SimpleNamespace(
        session_id=sid, user_id=user.id, tenant_id=other_tenant_id, title=None
    )
    db = _FakeSession(existing=existing)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as info:
        await chat_module._resolve_session(db, user, tenant, sid)
    assert info.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_session_recovers_from_integrity_race() -> None:
    """Two concurrent first-turn requests with the same UUID race on insert.
    The loser catches IntegrityError, rolls back, and re-reads the winner's
    row instead of bubbling a 500 up to the caller.
    """
    db = _FakeSession(integrity_on_commit=True)
    user = SimpleNamespace(id=uuid.uuid4())
    tenant = SimpleNamespace(id=uuid.uuid4())
    sid = str(uuid.uuid4())

    out = await chat_module._resolve_session(db, user, tenant, sid)

    assert out == sid
    assert db.rolled_back == 1


def test_resolve_session_no_longer_raises_404_on_missing_row() -> None:
    """Source guard — the strict 404 branch from pre-32.2 must not return."""
    src = inspect.getsource(chat_module._resolve_session)
    assert "session not found" not in src, (
        "_resolve_session must lazy-create unknown session ids, not 404"
    )
    assert "IntegrityError" in src, (
        "_resolve_session must handle PK race on concurrent first turns"
    )
