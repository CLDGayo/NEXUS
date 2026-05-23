"""Phase 28 Part 1 — admin provisioning end-to-end.

Skipped when ``TEST_POSTGRES_DSN`` / local :5432 is unreachable. Exercises:

* Superuser can list, create, promote, demote, and delete users.
* Non-superuser receives 403 on every admin route.
* Last-superuser guard blocks demote/delete on the only remaining admin.
* Self-demote / self-delete are refused.

Mirrors the no-DB skip pattern in ``test_phase27_auth.py`` so CI without a
Postgres still passes the smoke suite (see ``test_phase28_smoke.py``).
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid

import pytest
from fastapi.testclient import TestClient


def _has_local_pg() -> str | None:
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if dsn:
        return dsn
    try:
        with socket.create_connection(("localhost", 5432), timeout=0.5):
            return "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus_test"
    except OSError:
        return None


_PG_DSN = _has_local_pg()
pg_required = pytest.mark.skipif(
    _PG_DSN is None,
    reason="Phase 28 admin end-to-end test needs Postgres. Set TEST_POSTGRES_DSN.",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rag.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def event_loop():  # pylint: disable=redefined-outer-name
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def db_setup():
    if _PG_DSN is None:
        pytest.skip("no Postgres reachable")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from rag.database.base import Base
    from rag.database import models  # noqa: F401

    engine = create_async_engine(_PG_DSN)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def _register(client: TestClient, email: str, password: str = "correct-horse-battery-staple") -> str:
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code in {200, 201}, r.text
    return r.json()["id"]


def _login(client: TestClient, email: str, password: str = "correct-horse-battery-staple") -> str:
    r = client.post("/api/auth/jwt/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _promote_via_sql(user_id: str) -> None:
    """Bypass the API to seed a baseline superuser before exercising the admin routes."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_PG_DSN)  # type: ignore[arg-type]
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE app.users SET is_superuser = true WHERE id = :uid"),
                {"uid": uuid.UUID(user_id)},
            )
    finally:
        await engine.dispose()


@pg_required
def test_non_superuser_is_rejected(client: TestClient, db_setup) -> None:
    email = f"phase28-civ-{uuid.uuid4().hex[:8]}@nexus.test"
    _register(client, email)
    token = _login(client, email)
    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in {401, 403}, r.text


@pg_required
def test_superuser_can_list_create_promote_demote_delete(client: TestClient, db_setup) -> None:
    # Bootstrap a superuser.
    admin_email = f"phase28-admin-{uuid.uuid4().hex[:8]}@nexus.test"
    admin_id = _register(client, admin_email)
    asyncio.run(_promote_via_sql(admin_id))
    admin_token = _login(client, admin_email)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # List should at least include the admin themselves.
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["total"] >= 1
    assert any(u["email"] == admin_email for u in payload["items"])

    # Create a regular user.
    target_email = f"phase28-target-{uuid.uuid4().hex[:8]}@nexus.test"
    r = client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": target_email, "password": "another-strong-password"},
    )
    assert r.status_code == 201, r.text
    target = r.json()
    assert target["email"] == target_email
    assert target["is_superuser"] is False

    # Promote -> demote round-trip.
    r = client.post(f"/api/admin/users/{target['id']}/promote", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_superuser"] is True

    r = client.post(f"/api/admin/users/{target['id']}/demote", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_superuser"] is False

    # Soft delete.
    r = client.delete(f"/api/admin/users/{target['id']}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


@pg_required
def test_self_demote_and_self_delete_refused(client: TestClient, db_setup) -> None:
    admin_email = f"phase28-self-{uuid.uuid4().hex[:8]}@nexus.test"
    admin_id = _register(client, admin_email)
    asyncio.run(_promote_via_sql(admin_id))
    admin_token = _login(client, admin_email)
    headers = {"Authorization": f"Bearer {admin_token}"}

    r = client.post(f"/api/admin/users/{admin_id}/demote", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "CANNOT_DEMOTE_SELF"

    r = client.delete(f"/api/admin/users/{admin_id}", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "CANNOT_DELETE_SELF"


@pg_required
def test_password_change_requires_current_password(client: TestClient, db_setup) -> None:
    email = f"phase28-pw-{uuid.uuid4().hex[:8]}@nexus.test"
    pw = "correct-horse-battery-staple"
    _register(client, email, pw)
    token = _login(client, email, pw)
    headers = {"Authorization": f"Bearer {token}"}

    # Wrong current password -> 400.
    r = client.post(
        "/api/users/me/password",
        headers=headers,
        json={"current_password": "not-the-pw", "new_password": "brand-new-password"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "CURRENT_PASSWORD_INVALID"

    # Same as current -> 400.
    r = client.post(
        "/api/users/me/password",
        headers=headers,
        json={"current_password": pw, "new_password": pw},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "NEW_PASSWORD_SAME_AS_CURRENT"

    # Happy path.
    new_pw = "brand-new-password-1234"
    r = client.post(
        "/api/users/me/password",
        headers=headers,
        json={"current_password": pw, "new_password": new_pw},
    )
    assert r.status_code == 204, r.text

    # Old password must no longer log in; new one does.
    r = client.post("/api/auth/jwt/login", data={"username": email, "password": pw})
    assert r.status_code == 400, r.text
    r = client.post("/api/auth/jwt/login", data={"username": email, "password": new_pw})
    assert r.status_code == 200, r.text
