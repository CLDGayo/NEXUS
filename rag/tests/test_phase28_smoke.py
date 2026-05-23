"""Phase 28 Part 1 — smoke tests (no Postgres required).

Verifies that the new routes are mounted and reject anonymous traffic:
    * POST   /api/users/me/password
    * GET    /api/admin/users
    * POST   /api/admin/users
    * POST   /api/admin/users/{id}/promote
    * POST   /api/admin/users/{id}/demote
    * DELETE /api/admin/users/{id}

Full DB-backed behaviour (password rotation, promote/demote round-trip,
last-superuser guard) is covered by ``test_phase28_admin_users.py`` which is
skipped when Postgres is unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rag.main import app

    return TestClient(app)


def test_password_change_route_mounted(client: TestClient) -> None:
    """POST /api/users/me/password rejects anonymous callers with 401."""
    response = client.post(
        "/api/users/me/password",
        json={"current_password": "x", "new_password": "yyyyyyyy"},
    )
    assert response.status_code == 401, response.text


def test_password_change_requires_body(client: TestClient) -> None:
    """Body validation (min_length=8 on new_password) is enforced even when
    the caller is unauthenticated — auth is checked LAST in the dependency
    chain after Pydantic when the request body is malformed.

    The endpoint should never 404. Accepting any 4xx confirms the route is
    mounted and routable.
    """
    response = client.post("/api/users/me/password", json={})
    assert response.status_code != 404, response.text
    assert response.status_code in {401, 422}, response.text


def test_admin_users_list_requires_auth(client: TestClient) -> None:
    """GET /api/admin/users rejects anonymous callers."""
    response = client.get("/api/admin/users")
    assert response.status_code == 401, response.text


def test_admin_users_create_requires_auth(client: TestClient) -> None:
    """POST /api/admin/users rejects anonymous callers."""
    response = client.post(
        "/api/admin/users",
        json={"email": "x@nexus.test", "password": "yyyyyyyy"},
    )
    assert response.status_code == 401, response.text


def test_admin_users_promote_requires_auth(client: TestClient) -> None:
    fake_id = uuid.uuid4()
    response = client.post(f"/api/admin/users/{fake_id}/promote")
    assert response.status_code == 401, response.text


def test_admin_users_demote_requires_auth(client: TestClient) -> None:
    fake_id = uuid.uuid4()
    response = client.post(f"/api/admin/users/{fake_id}/demote")
    assert response.status_code == 401, response.text


def test_admin_users_delete_requires_auth(client: TestClient) -> None:
    fake_id = uuid.uuid4()
    response = client.delete(f"/api/admin/users/{fake_id}")
    assert response.status_code == 401, response.text


def test_conversations_list_requires_auth(client: TestClient) -> None:
    """Phase 28 Part 1 — conversations router switched from legacy admin JWT
    to ``current_active_user``. Anonymous callers must now receive 401, not
    a leak of every conversation in the database."""
    response = client.get("/api/conversations")
    assert response.status_code == 401, response.text


def test_conversation_detail_requires_auth(client: TestClient) -> None:
    response = client.get("/api/conversations/some-id")
    assert response.status_code == 401, response.text
