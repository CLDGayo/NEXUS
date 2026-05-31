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

Phase 32.6 — adds HEAD support. Meta's Send API validates ``image_url``
via a HEAD probe before queueing carousel deliveries; a GET-only route
responds 405 and Meta surfaces ``(#100) ... should represent a valid
URL``, 400-DLQ'ing every carousel send. HEAD uses ``head_object`` so we
return the right headers (``Content-Type``, ``Content-Length``) without
paying the body-fetch cost on every validation probe.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from rag.services import object_proxy, object_store

_log = logging.getLogger(__name__)

router = APIRouter(tags=["objects"])


@router.api_route("/objects/{token}", methods=["GET", "HEAD"])
async def get_object(token: str, request: Request) -> Response:
    bucket, key = object_proxy.decode_token(token)

    if request.method == "HEAD":
        async with object_store.s3_client() as client:
            try:
                head: dict[str, Any] = await client.head_object(Bucket=bucket, Key=key)
            except client.exceptions.NoSuchKey as exc:  # type: ignore[attr-defined]
                raise HTTPException(status_code=404, detail="object_not_found") from exc
            except Exception as exc:  # noqa: BLE001 — surface a clean 502 to the caller
                # botocore raises ClientError with a 404-coded response for
                # Minio HEAD misses (the typed NoSuchKey alias isn't always
                # populated for head_object). Treat any "Code: 404/NoSuchKey/
                # NotFound" as a clean 404 so Meta gets a deterministic signal.
                response_meta = getattr(exc, "response", None)
                err_code: str | None = None
                if isinstance(response_meta, dict):
                    err_code = str(response_meta.get("Error", {}).get("Code") or "")
                if err_code in {"404", "NoSuchKey", "NotFound"}:
                    raise HTTPException(
                        status_code=404, detail="object_not_found"
                    ) from exc
                _log.warning(
                    "objects.head_failed bucket=%s key=%s detail=%s", bucket, key, exc
                )
                raise HTTPException(status_code=502, detail="object_fetch_failed") from exc

        content_type = head.get("ContentType") or "application/octet-stream"
        content_length = int(head.get("ContentLength") or 0)
        return Response(
            status_code=200,
            media_type=content_type,
            headers={
                "Cache-Control": "private, max-age=3600",
                "Content-Length": str(content_length),
            },
        )

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
