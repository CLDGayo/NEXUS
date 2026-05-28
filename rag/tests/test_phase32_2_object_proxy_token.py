"""Phase 32.2 — signed object-proxy token round-trip + tamper resistance."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from jose import jwt

from rag.services import object_proxy


def test_mint_decode_round_trip() -> None:
    token = object_proxy.mint_token("nexus-products", "tenant-a/prod-1/img-1.webp")
    bucket, key = object_proxy.decode_token(token)
    assert bucket == "nexus-products"
    assert key == "tenant-a/prod-1/img-1.webp"


def test_proxy_url_is_spa_relative() -> None:
    url = object_proxy.proxy_url("nexus-products", "x/y.webp")
    assert url.startswith("/api/objects/")
    # Token should be non-empty after the prefix.
    assert len(url) > len("/api/objects/")


def test_token_expired_rejected() -> None:
    token = object_proxy.mint_token("b", "k", expires_in=1)
    # Use a short expiry then sleep past it.
    time.sleep(2)
    with pytest.raises(HTTPException) as info:
        object_proxy.decode_token(token)
    assert info.value.status_code == 401


def test_tampered_token_rejected() -> None:
    token = object_proxy.mint_token("b", "k")
    # Flip the last character of the signature segment to invalidate.
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(HTTPException) as info:
        object_proxy.decode_token(tampered)
    assert info.value.status_code == 401


def test_token_with_wrong_audience_rejected() -> None:
    # Forge a token signed with the right secret but a different audience.
    fake = jwt.encode(
        {"b": "x", "k": "y", "aud": "not-nexus", "exp": int(time.time()) + 60},
        object_proxy._secret(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as info:
        object_proxy.decode_token(fake)
    assert info.value.status_code == 401


def test_mint_rejects_empty_bucket_or_key() -> None:
    with pytest.raises(ValueError):
        object_proxy.mint_token("", "k")
    with pytest.raises(ValueError):
        object_proxy.mint_token("b", "")


def test_malformed_payload_rejected() -> None:
    # Signed token but missing b/k fields → 400.
    bad = jwt.encode(
        {"aud": object_proxy._AUDIENCE, "exp": int(time.time()) + 60},
        object_proxy._secret(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as info:
        object_proxy.decode_token(bad)
    assert info.value.status_code == 400
