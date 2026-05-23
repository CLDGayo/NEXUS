"""Phase 27 Part 2 — POST /api/auth/login is permanently gone.

Stale SPA builds and any external automation that still hits the legacy shim
must receive a deterministic ``410 Gone`` with a pointer at the canonical
fastapi-users login endpoint instead of a confusing ``404``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rag.main import app

    return TestClient(app)


def test_legacy_login_returns_410(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "anything"})
    assert response.status_code == 410, response.text
    detail = response.json().get("detail", "")
    assert "Use POST /api/auth/jwt/login" in detail, detail


def test_legacy_login_410_ignores_body_shape(client: TestClient) -> None:
    """No body at all — still 410, never 422. The shim has no schema to
    validate against post-deprecation."""
    response = client.post("/api/auth/login")
    assert response.status_code == 410, response.text
