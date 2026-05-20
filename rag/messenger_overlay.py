"""Filesystem overlay for Messenger token rotation.

Backstory: ``MESSENGER_VERIFY_TOKEN`` and ``MESSENGER_PAGE_ACCESS_TOKEN``
are env-driven for first boot, but the UI needs to let the admin rotate
either without editing ``.env`` on the VPS (mirrors the password / JWT
overlay pattern in :mod:`auth_overlay`).

Overrides persist to ``data/.messenger_override.json`` (mode 600). Env
values are the fallback; overlay always wins when present.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

_OVERLAY_PATH = Path(__file__).parent / "data" / ".messenger_override.json"

_MIN_TOKEN_LEN = 16
_VERIFY_TOKEN_BYTES = 32


def _read_overlay() -> dict[str, str]:
    if not _OVERLAY_PATH.exists():
        return {}
    try:
        return json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_overlay(data: dict[str, str]) -> None:
    _OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _OVERLAY_PATH.with_suffix(_OVERLAY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _OVERLAY_PATH)
    try:
        os.chmod(_OVERLAY_PATH, 0o600)
    except OSError:
        pass


def current_verify_token() -> str | None:
    overlay = _read_overlay()
    val = overlay.get("verify_token")
    if val:
        return val
    env_val = os.environ.get("MESSENGER_VERIFY_TOKEN")
    return env_val or None


def current_page_access_token() -> str | None:
    overlay = _read_overlay()
    val = overlay.get("page_access_token")
    if val:
        return val
    env_val = os.environ.get("MESSENGER_PAGE_ACCESS_TOKEN")
    return env_val or None


def current_app_secret() -> str | None:
    overlay = _read_overlay()
    val = overlay.get("app_secret")
    if val:
        return val
    env_val = os.environ.get("MESSENGER_APP_SECRET")
    return env_val or None


def set_verify_token(value: str) -> None:
    if not value or len(value) < _MIN_TOKEN_LEN:
        raise ValueError(f"verify_token must be at least {_MIN_TOKEN_LEN} characters")
    overlay = _read_overlay()
    overlay["verify_token"] = value
    _write_overlay(overlay)


def set_page_access_token(value: str) -> None:
    if not value or len(value) < _MIN_TOKEN_LEN:
        raise ValueError(
            f"page_access_token must be at least {_MIN_TOKEN_LEN} characters"
        )
    overlay = _read_overlay()
    overlay["page_access_token"] = value
    _write_overlay(overlay)


def set_app_secret(value: str) -> None:
    if not value or len(value) < _MIN_TOKEN_LEN:
        raise ValueError(
            f"app_secret must be at least {_MIN_TOKEN_LEN} characters"
        )
    overlay = _read_overlay()
    overlay["app_secret"] = value
    _write_overlay(overlay)


def mask_app_secret(secret: str | None) -> str | None:
    """Render an app secret for read-only display."""
    return mask_page_access_token(secret)


def rotate_verify_token() -> str:
    new_token = secrets.token_urlsafe(_VERIFY_TOKEN_BYTES)
    overlay = _read_overlay()
    overlay["verify_token"] = new_token
    _write_overlay(overlay)
    return new_token


def mask_page_access_token(token: str | None) -> str | None:
    """Render a PAT for read-only display: first 4 + last 4, rest masked."""
    if not token:
        return None
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}{'•' * 8}{token[-4:]}"
