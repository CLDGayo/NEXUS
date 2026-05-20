"""Tests for the Messenger token overlay (Phase 11).

Mirrors the pattern in test_new_pages.py: monkeypatch the overlay path
to a tmp_path location and exercise read/write/rotate.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def overlay_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    overlay_file = tmp_path / ".messenger_override.json"
    monkeypatch.delenv("MESSENGER_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_PAGE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_APP_SECRET", raising=False)

    import messenger_overlay
    importlib.reload(messenger_overlay)
    monkeypatch.setattr(messenger_overlay, "_OVERLAY_PATH", overlay_file)
    return messenger_overlay


@pytest.mark.unit
def test_current_tokens_default_to_none(overlay_mod):
    assert overlay_mod.current_verify_token() is None
    assert overlay_mod.current_page_access_token() is None
    assert overlay_mod.current_app_secret() is None


@pytest.mark.unit
def test_env_provides_fallback(overlay_mod, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MESSENGER_VERIFY_TOKEN", "env-verify-token-value")
    monkeypatch.setenv("MESSENGER_PAGE_ACCESS_TOKEN", "env-pat-EAA-blah-blah")
    monkeypatch.setenv("MESSENGER_APP_SECRET", "env-secret-xyz")

    assert overlay_mod.current_verify_token() == "env-verify-token-value"
    assert overlay_mod.current_page_access_token() == "env-pat-EAA-blah-blah"
    assert overlay_mod.current_app_secret() == "env-secret-xyz"


@pytest.mark.unit
def test_overlay_overrides_env(overlay_mod, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MESSENGER_VERIFY_TOKEN", "env-verify-token-value")
    overlay_mod.set_verify_token("overlay-token-rotated-secret")
    assert overlay_mod.current_verify_token() == "overlay-token-rotated-secret"


@pytest.mark.unit
def test_overlay_app_secret_overrides_env(
    overlay_mod, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MESSENGER_APP_SECRET", "env-app-secret-value-AAAA")
    overlay_mod.set_app_secret("overlay-app-secret-value-BBBB")
    assert overlay_mod.current_app_secret() == "overlay-app-secret-value-BBBB"


@pytest.mark.unit
def test_set_app_secret_rejects_short(overlay_mod):
    with pytest.raises(ValueError):
        overlay_mod.set_app_secret("too-short")


@pytest.mark.unit
def test_set_app_secret_persists(overlay_mod):
    overlay_mod.set_app_secret("real-app-secret-with-32-chars-X")
    assert overlay_mod.current_app_secret() == "real-app-secret-with-32-chars-X"


@pytest.mark.unit
def test_rotate_verify_token_generates_new_value(overlay_mod):
    first = overlay_mod.rotate_verify_token()
    second = overlay_mod.rotate_verify_token()
    assert first != second
    assert len(first) >= 16
    assert overlay_mod.current_verify_token() == second


@pytest.mark.unit
def test_set_verify_token_rejects_short(overlay_mod):
    with pytest.raises(ValueError):
        overlay_mod.set_verify_token("too-short")


@pytest.mark.unit
def test_set_page_access_token_rejects_short(overlay_mod):
    with pytest.raises(ValueError):
        overlay_mod.set_page_access_token("short")


@pytest.mark.unit
def test_set_page_access_token_persists(overlay_mod):
    overlay_mod.set_page_access_token("EAA-page-access-token-12345")
    assert overlay_mod.current_page_access_token() == "EAA-page-access-token-12345"


@pytest.mark.unit
def test_overlay_file_permissions(overlay_mod):
    overlay_mod.set_verify_token("a-token-with-enough-chars-here")
    import os
    mode = os.stat(overlay_mod._OVERLAY_PATH).st_mode & 0o777
    assert mode == 0o600


@pytest.mark.unit
def test_mask_page_access_token():
    from messenger_overlay import mask_page_access_token
    assert mask_page_access_token(None) is None
    assert mask_page_access_token("") is None
    assert mask_page_access_token("EAA-abc-secret-1234") == "EAA-••••••••1234"
    assert mask_page_access_token("short") == "•••••"
