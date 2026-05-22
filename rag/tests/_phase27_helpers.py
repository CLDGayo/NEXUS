"""Shared overrides for legacy chat tests post-Phase 27 lockdown.

Phase 27 swapped ``/api/chat/stream`` from legacy admin JWTs to
``current_active_user`` (fastapi-users). The legacy integration tests that
log in via ``POST /api/auth/login`` and reuse the bearer token can't be
updated to a full register→jwt-login flow without standing up Postgres in
the unit-test environment. We instead override the two FastAPI dependencies
for the duration of those tests so they exercise the routing + persistence
behavior they care about, not the auth wiring (which is covered separately
by ``test_phase27_auth.py``).
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock

from fastapi import FastAPI


class _FakeUser:
    """Just enough of ``rag.database.models.User`` for the route to function.

    fastapi-users users are SQLAlchemy rows in production; for tests we only
    need a stable ``.id`` attribute that round-trips through ``str()``.
    """

    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        self.email = "test-admin@nexus.test"
        self.is_active = True
        self.is_superuser = True
        self.is_verified = True


def install_chat_test_overrides(app: FastAPI, *, user: _FakeUser | None = None) -> _FakeUser:
    """Inject fake auth + DB session into the app's dependency overrides.

    Returns the user object so tests can inspect it (or assert it was used).
    Re-installable: calling this twice replaces the previous overrides.
    """
    from rag.auth import current_active_user
    from rag.database.engine import get_async_session

    fake_user = user or _FakeUser()

    async def _override_user() -> _FakeUser:
        return fake_user

    async def _override_session() -> AsyncIterator[AsyncMock]:
        session = AsyncMock()
        # _resolve_session() calls db.get(ChatSession, id) — return None so the
        # 404 branch runs only when a session_id is supplied. Tests that pass
        # session_id=None hit the "mint new session_id" branch which uses
        # db.add + db.commit — those are AsyncMock no-ops on the session.
        session.get = AsyncMock(return_value=None)
        session.commit = AsyncMock(return_value=None)
        session.add = lambda obj: None  # sync in SQLA's real API
        yield session

    app.dependency_overrides[current_active_user] = _override_user
    app.dependency_overrides[get_async_session] = _override_session
    return fake_user


def install_legacy_login_shim_override(
    monkeypatch, app: FastAPI, *, user: _FakeUser | None = None
) -> _FakeUser:
    """Phase 27 Part 1.1 — make the legacy ``POST /api/auth/login`` shim
    succeed in tests without a real Postgres.

    Monkeypatches ``routers.auth._load_designated_superuser`` to return a
    canned superuser row and pins the same fake user on the app's
    ``current_active_user`` + ``get_async_session`` dependency overrides so
    downstream calls (e.g. ``/api/chat/stream``) accept the JWT the shim
    mints.
    """
    fake = install_chat_test_overrides(app, user=user)

    async def _fake_superuser_lookup(_db):  # noqa: ANN001
        return fake

    import routers.auth as legacy_auth

    monkeypatch.setattr(
        legacy_auth, "_load_designated_superuser", _fake_superuser_lookup
    )
    return fake
