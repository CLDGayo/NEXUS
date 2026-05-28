"""Phase 32.2 — signed-token proxy URLs for private MinIO objects.

Production runs MinIO on the internal docker network (`http://nexus-minio:9000`)
with no host port mapping and no public DNS entry. Any presigned URL boto3
generates therefore embeds an unreachable hostname, so ``<img src>`` cannot
render product images.

Rather than expose MinIO publicly, we mint a short-lived signed token that
identifies one specific ``(bucket, key)`` pair and serve the bytes through
the existing FastAPI app (``GET /api/objects/{token}``). The token uses
``settings.nexus_jwt_secret`` so it cannot be forged without the server's
JWT secret; a leaked token works for ≤ ``expires_in`` seconds on exactly
one object.

The serializer side (``rag.routers.products._mint_image_url``) calls
``proxy_url`` to embed ``/api/objects/<token>`` in product image responses.
The route side (``rag.routers.objects.get_object``) calls ``decode_token``
to recover the bucket/key, fetch via the internal s3 client, and stream
the body back to the browser.
"""

from __future__ import annotations

import time
from typing import Final

from fastapi import HTTPException
from jose import JWTError, jwt

from rag.config import settings

_ALGORITHM: Final[str] = "HS256"
_AUDIENCE: Final[str] = "nexus:object-proxy"


def _secret() -> str:
    """Return the JWT signing secret. Falls back to the test secret used by
    the auth manager so unit tests do not have to set ``NEXUS_JWT_SECRET``."""
    return settings.nexus_jwt_secret or "test-nexus-jwt-secret"


def mint_token(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Return a signed token authorising a GET on ``(bucket, key)`` for
    ``expires_in`` seconds. The token is opaque to the caller."""
    if not bucket or not key:
        raise ValueError("bucket and key are required to mint an object token")
    now = int(time.time())
    payload = {
        "b": bucket,
        "k": key,
        "iat": now,
        "exp": now + int(expires_in),
        "aud": _AUDIENCE,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> tuple[str, str]:
    """Verify ``token`` and return its ``(bucket, key)``.

    Raises ``HTTPException(401)`` on signature / audience / expiry failure
    and ``HTTPException(400)`` on a structurally bad payload.
    """
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_object_token") from exc

    bucket = payload.get("b")
    key = payload.get("k")
    if not isinstance(bucket, str) or not isinstance(key, str) or not bucket or not key:
        raise HTTPException(status_code=400, detail="malformed_object_token")
    return bucket, key


def proxy_url(bucket: str, key: str, *, expires_in: int = 3600) -> str:
    """Return the SPA-relative URL the browser hits to fetch ``(bucket, key)``.

    The URL is mounted under the same origin as the SPA, so cookies and
    CORS are not in play and the token itself is the only authorisation.
    """
    token = mint_token(bucket, key, expires_in=expires_in)
    return f"/api/objects/{token}"
