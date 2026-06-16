"""Phase 55/56 — token encryption-at-rest helper."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

import rag.crypto as crypto


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.settings, "nexus_token_encryption_key", key)
    crypto._fernet.cache_clear()
    yield key
    crypto._fernet.cache_clear()


@pytest.mark.unit
def test_roundtrip(fernet_key):
    ct = crypto.encrypt_token("page-access-token-xyz")
    assert ct != "page-access-token-xyz"
    assert crypto.decrypt_token(ct) == "page-access-token-xyz"


@pytest.mark.unit
def test_two_encryptions_differ_but_decrypt_same(fernet_key):
    a = crypto.encrypt_token("same")
    b = crypto.encrypt_token("same")
    assert a != b  # Fernet embeds a random IV + timestamp
    assert crypto.decrypt_token(a) == crypto.decrypt_token(b) == "same"


@pytest.mark.unit
def test_tampered_ciphertext_returns_none(fernet_key):
    assert crypto.decrypt_token("not-valid-fernet") is None
    ct = crypto.encrypt_token("x")
    assert crypto.decrypt_token(ct[:-2] + "AA") is None  # bit-flipped tail


@pytest.mark.unit
def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(crypto.settings, "nexus_token_encryption_key", "")
    crypto._fernet.cache_clear()
    with pytest.raises(RuntimeError):
        crypto.encrypt_token("x")
    crypto._fernet.cache_clear()
