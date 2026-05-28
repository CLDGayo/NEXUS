"""Phase 32.2 — Public-byte-proxy for signed MinIO object URLs.

``GET /api/objects/{token}`` is intentionally un-authenticated: the token
itself is the authorisation. ``rag.services.object_proxy.mint_token`` is
only ever called by code paths that have already enforced their own
owner/tenant checks (today: ``rag.routers.products._mint_image_url`` runs
inside owner-gated routes). A stolen token is scoped to one object for
≤ 1 hour, matching the blast radius of a presigned URL.

This route exists because production MinIO runs only on the internal
docker network. If a public MinIO endpoint is added later, the products
router will pick up ``settings.minio_public_base_url`` first and the
proxy becomes a no-op fallback.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from rag.services import object_proxy, object_store

_log = logging.getLogger(__name__)

router = APIRouter(tags=["objects"])


@router.get("/objects/{token}")
async def get_object(token: str) -> StreamingResponse:
    bucket, key = object_proxy.decode_token(token)

    async with object_store.s3_client() as client:
        try:
            obj: dict[str, Any] = await client.get_object(Bucket=bucket, Key=key)
        except client.exceptions.NoSuchKey as exc:  # type: ignore[attr-defined]
            raise HTTPException(status_code=404, detail="object_not_found") from exc
        except Exception as exc:  # noqa: BLE001 — surface a clean 502 to the caller
            _log.warning("objects.get_failed bucket=%s key=%s detail=%s", bucket, key, exc)
            raise HTTPException(status_code=502, detail="object_fetch_failed") from exc

        body = obj["Body"]
        content_type = obj.get("ContentType") or "application/octet-stream"
        # ``read()`` drains the StreamingBody inside the s3_client context so
        # the underlying connection is released before we return. Product
        # images are bounded by ``settings.product_image_max_dim`` (1200px
        # WebP, ~150KB typical, 5MB hard cap), so buffering is acceptable.
        data = await body.read()

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Length": str(len(data)),
        },
    )
