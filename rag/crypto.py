"""Symmetric encryption-at-rest helper for third-party OAuth/page tokens.

Phase 55/56 — NEXUS stores long-lived Facebook Page/User access tokens and
Google OAuth access tokens in Postgres. Those are bearer credentials, so they
must never sit in the database as plaintext. This module wraps
``cryptography.fernet`` (AES-128-CBC + HMAC-SHA256, authenticated) behind two
tiny functions so callers never touch key material directly.

The key lives in ``settings.nexus_token_encryption_key`` (env
``NEXUS_TOKEN_ENCRYPTION_KEY``) — a urlsafe-base64 32-byte Fernet key,
generated once with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotating the key invalidates existing ciphertext; ``decrypt_token`` returns
``None`` on any token that no longer verifies (tampered or key-rotated) so the
caller can treat it as "must reconnect" rather than crashing.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from rag.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.nexus_token_encryption_key
    if not key:
        raise RuntimeError(
            "NEXUS_TOKEN_ENCRYPTION_KEY is unset — cannot encrypt/decrypt "
            "third-party tokens. Generate one with Fernet.generate_key()."
        )
    # Fernet validates the key length/format and raises ValueError early if
    # the operator pasted a malformed key, which is what we want at boot.
    return Fernet(key.encode("utf-8"))


def encrypt_token(plaintext: str) -> str:
    """Return urlsafe-base64 Fernet ciphertext for ``plaintext``."""

    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str | None:
    """Decrypt ``ciphertext``; return ``None`` if it no longer verifies.

    A ``None`` return means the stored token is unusable (tampered, corrupted,
    or encrypted under a rotated key) — callers should treat it as a revoked
    credential and prompt the tenant to reconnect rather than raise.
    """

    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
