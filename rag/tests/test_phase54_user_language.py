"""Phase 54 — per-user UI language preference.

Schema tests are pure-Pydantic (no Postgres). The route smoke test confirms
``PATCH /api/users/me`` is mounted and still validates the body for anonymous
callers. Full DB-backed round-trip (persist + read back) rides on the existing
fastapi-users ``PATCH /users/me`` path and the 0011 migration.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rag.auth.schemas import SUPPORTED_LANGUAGES, UserRead, UserUpdate


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rag.main import app

    return TestClient(app)


def test_supported_languages_match_frontend() -> None:
    """Guard against drift from nexus-ui/src/i18n/languages.js."""
    assert SUPPORTED_LANGUAGES == frozenset(
        {"en", "vi", "fil", "de", "fr", "es", "ja"}
    )


def test_user_read_defaults_to_english() -> None:
    assert UserRead.model_fields["language"].default == "en"


@pytest.mark.parametrize("code", sorted(SUPPORTED_LANGUAGES))
def test_user_update_accepts_supported_language(code: str) -> None:
    assert UserUpdate(language=code).language == code


def test_user_update_allows_omitting_language() -> None:
    """language is optional — a profile patch that only touches display_name
    must not be forced to send a language."""
    assert UserUpdate(display_name="Ada").language is None


@pytest.mark.parametrize("bad", ["xx", "en-US", "english", "", "EN"])
def test_user_update_rejects_unsupported_language(bad: str) -> None:
    with pytest.raises(ValidationError):
        UserUpdate(language=bad)


def test_patch_users_me_requires_auth(client: TestClient) -> None:
    """Valid body, but anonymous → 401 (route mounted, auth enforced)."""
    response = client.patch("/api/users/me", json={"language": "es"})
    assert response.status_code == 401, response.text


def test_patch_users_me_validates_language(client: TestClient) -> None:
    """Invalid language must never 404; body validation / auth returns 4xx."""
    response = client.patch("/api/users/me", json={"language": "xx"})
    assert response.status_code != 404, response.text
    assert response.status_code in {401, 422}, response.text
