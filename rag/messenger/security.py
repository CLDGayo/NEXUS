"""Shared-secret auth for Phase 2 webhook endpoints.

The orchestrator (n8n / Make) must include the ``X-Webhook-Api-Key`` header
matching ``WEBHOOK_API_KEY`` in the environment. Phase 8 will additionally
validate Facebook's ``X-Hub-Signature-256`` HMAC when the orchestrator
forwards the raw Graph API body.

We use ``hmac.compare_digest`` to short-circuit timing attacks against the
key comparison.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from rag.config import settings


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
