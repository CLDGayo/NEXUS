"""Phase 15 — Multimodal image upload for the chat surface.

Accepts a single image, validates MIME + size, and returns a base64 data URI
the SPA can embed in the next ``/api/chat/stream`` request as an attachment.

The route is stateless: nothing is written to disk or the database. The data
URI lives only for the duration of the chat turn that consumes it.
"""

from __future__ import annotations

from base64 import b64encode
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from rag.config import settings
from routers.deps import require_auth_or_token

router = APIRouter(tags=["chat"])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@router.post(
    "/upload",
    dependencies=[Depends(require_auth_or_token("chat:write"))],
)
async def chat_upload(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported extension {ext!r}. Allowed: .jpg, .jpeg, .png, .webp",
        )

    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type {mime!r}. Allowed: image/jpeg, image/png, image/webp",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")
    if len(data) > settings.vision_upload_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {settings.vision_upload_max_bytes} bytes",
        )

    b64 = b64encode(data).decode("ascii")
    return {
        "url": f"data:{mime};base64,{b64}",
        "mime": mime,
        "size_bytes": len(data),
    }
