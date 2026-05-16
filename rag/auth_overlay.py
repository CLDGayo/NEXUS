"""Filesystem overlay for password + JWT secret rotation.

Backstory: `NEXUS_PASSWORD` and `JWT_SECRET` are env-driven for first boot, but
the UI needs to let the admin rotate either without editing `.env` on the VPS.
This module persists overrides to `data/.password_override.json` (mode 600).
Env values are the fallback; overlay always wins when present.

Password is stored as scrypt(salt + plaintext) — no plaintext ever lands on disk.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

_OVERLAY_PATH = Path(__file__).parent / "data" / ".password_override.json"

# scrypt parameters — moderate cost; this runs once per login.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


def _read_overlay() -> dict[str, str]:
    if not _OVERLAY_PATH.exists():
        return {}
    try:
        return json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_overlay(data: dict[str, str]) -> None:
    _OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OVERLAY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(_OVERLAY_PATH, 0o600)
    except OSError:
        pass


def _hash(password: str, salt_hex: str) -> str:
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return derived.hex()


def verify_password(plain: str) -> bool:
    """Constant-time compare against overlay or env-default."""
    overlay = _read_overlay()
    if "password_hash" in overlay and "password_salt" in overlay:
        candidate = _hash(plain, overlay["password_salt"])
        return hmac.compare_digest(candidate, overlay["password_hash"])

    env_pw = os.environ.get("NEXUS_PASSWORD", "changeme")
    return hmac.compare_digest(plain.encode("utf-8"), env_pw.encode("utf-8"))


def set_password(new_plain: str) -> None:
    if not new_plain or len(new_plain) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt_hex = secrets.token_hex(_SALT_BYTES)
    overlay = _read_overlay()
    overlay["password_salt"] = salt_hex
    overlay["password_hash"] = _hash(new_plain, salt_hex)
    _write_overlay(overlay)


def current_jwt_secret() -> str:
    overlay = _read_overlay()
    if "jwt_secret" in overlay and overlay["jwt_secret"]:
        return overlay["jwt_secret"]
    return os.environ.get("JWT_SECRET", "dev-secret-change-this")


def rotate_jwt_secret() -> str:
    new_secret = secrets.token_urlsafe(48)
    overlay = _read_overlay()
    overlay["jwt_secret"] = new_secret
    _write_overlay(overlay)
    return new_secret
