"""Shared-secret auth + Meta signature verification for webhook endpoints.

Two auth surfaces live here:

* ``require_webhook_api_key`` — Phase 6 broker path. The orchestrator
  (n8n / Make) must include ``X-Webhook-Api-Key`` matching
  ``WEBHOOK_API_KEY`` in the env.

* ``verify_meta_signature`` — Phase 12 direct path. When Meta calls our
  webhook itself, the request body is HMAC-SHA256-signed in the
  ``X-Hub-Signature-256`` header with the Facebook App Secret. The signing
  key is read live from :mod:`rag.messenger_overlay` so a UI rotation
  takes effect without restart.

Both helpers use ``hmac.compare_digest`` to short-circuit timing attacks
against the key comparison.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, status

from rag.config import settings
from rag.messenger_overlay import current_app_secret


async def require_webhook_api_key(
    x_webhook_api_key: str | None = Header(default=None, alias="X-Webhook-Api-Key"),
) -> None:
    """FastAPI dependency that 401s any request missing/mismatching the key.

    Fails closed if ``WEBHOOK_API_KEY`` is not configured — silently
    accepting anonymous traffic would defeat the auth surface.
    """

    expected = settings.webhook_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook auth not configured",
        )
    if not x_webhook_api_key or not hmac.compare_digest(x_webhook_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing webhook api key",
        )


def verify_meta_signature(raw_body: bytes, header_value: str | None) -> None:
    """Verify Meta's ``X-Hub-Signature-256`` header against ``raw_body``.

    The expected header form is ``"sha256=<hexdigest>"``. The signing key
    is the Facebook App Secret read live from
    :func:`rag.messenger_overlay.current_app_secret`, so rotating the
    secret in the env file + restarting takes effect immediately (the
    overlay does not store the app secret — it stays env-only by design,
    same as the Phase 11 module).

    Raises ``HTTPException(503)`` when the secret is unset and
    ``HTTPException(403)`` on any signature mismatch.
    """

    secret = current_app_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="messenger app secret not configured",
        )

    if not header_value or not header_value.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="missing or malformed signature",
        )

    provided = header_value[len("sha256=") :].strip()
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="signature mismatch",
        )
