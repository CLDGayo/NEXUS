"""Phase 28 — authenticated user self-service profile router.

Part 1 shipped ``POST /api/users/me/password``: requires the caller to prove
ownership of the existing password before the new one is accepted. The
built-in ``PATCH /api/users/me`` from fastapi-users does NOT enforce that
check, so the SPA profile page calls this endpoint instead. ``PATCH
/api/users/me`` remains available for non-credential mutations
(display_name, profile_image_url).

Part 2 adds Minio-backed avatar uploads:

    POST   /api/users/me/avatar       — multipart image, normalised to WebP
    DELETE /api/users/me/avatar       — clears profile_image_url + Minio blob
    GET    /api/users/me/avatar/url   — fresh presigned URL (1h)

Storage layout: ``{minio_bucket_avatars}/{user_uuid}.webp``. When
``settings.minio_public_base_url`` is non-empty we persist a stable public
URL on the user row (CDN / nginx proxy); otherwise the URL field stays
empty and the SPA calls ``/avatar/url`` to mint presigned URLs on demand.
"""

from __future__ import annotations

import io
import logging
from typing import Final

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_active_user
from rag.auth.manager import UserManager, get_user_manager
from rag.auth.schemas import UserRead, UserUpdate
from rag.config import settings
from rag.database.engine import get_async_session
from rag.database.models import User
from rag.services import object_store

_log = logging.getLogger(__name__)

router = APIRouter(tags=["profile"])

_ALLOWED_MIME: Final = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)
_AVATAR_CONTENT_TYPE: Final = "image/webp"


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=256)


class AvatarUrlResponse(BaseModel):
    url: str
    expires_in: int


def _avatar_key(user: User) -> str:
    return f"{user.id}.webp"


def _resolve_avatar_display_url(key: str) -> str | None:
    """Return the URL we persist on ``profile_image_url``.

    Public CDN configured → stable HTTPS URL; otherwise None so the SPA
    knows to fetch a fresh presigned URL on read.
    """
    return object_store.public_url_for(key)


def _normalise_to_webp(raw: bytes, *, size: int) -> bytes:
    """Decode arbitrary user input, downscale to ``size×size`` WebP.

    Validates the byte stream is an actual image (not e.g. a renamed .exe)
    and strips EXIF metadata in the process. Raises ``HTTPException(415)``
    when Pillow cannot decode.
    """
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            # ``thumbnail`` keeps aspect ratio and never enlarges — combine
            # with a square paste so the final blob is exactly size×size.
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (size, size), (255, 255, 255))
            paste_x = (size - img.width) // 2
            paste_y = (size - img.height) // 2
            canvas.paste(img, (paste_x, paste_y))
            out = io.BytesIO()
            canvas.save(out, format="WEBP", quality=85, method=6)
            return out.getvalue()
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=415, detail="UNSUPPORTED_IMAGE_FORMAT"
        ) from exc


@router.post("/me/password", status_code=204, response_class=Response)
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Response:
    """Verify the current password, then rotate to ``new_password``.

    Returns 204 on success, 400 ``CURRENT_PASSWORD_INVALID`` when the supplied
    current password does not match the stored hash, and 422 (Pydantic) when
    the new password is shorter than 8 characters.
    """

    valid, _new_hash = user_manager.password_helper.verify_and_update(
        body.current_password, user.hashed_password
    )
    if not valid:
        raise HTTPException(
            status_code=400, detail="CURRENT_PASSWORD_INVALID"
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="NEW_PASSWORD_SAME_AS_CURRENT"
        )

    await user_manager.update(
        UserUpdate(password=body.new_password), user, safe=True
    )
    _log.info("auth.password_changed user_id=%s", str(user.id))
    return Response(status_code=204)


@router.post("/me/avatar", response_model=UserRead)
async def upload_avatar(
    file: UploadFile = File(..., description="JPG / PNG / WEBP, ≤2 MB."),
    user: User = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
    session: AsyncSession = Depends(get_async_session),
) -> UserRead:
    """Accept an image upload, normalise it, persist to Minio + user row."""
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"UNSUPPORTED_MIME ({file.content_type or 'unknown'})",
        )

    # Cap the in-memory read to the configured ceiling +1 so we can detect
    # oversize without buffering hundreds of MB.
    limit = settings.avatar_max_upload_bytes
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"AVATAR_TOO_LARGE (limit {limit} bytes)",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="EMPTY_BODY")

    normalised = _normalise_to_webp(raw, size=settings.avatar_output_size)

    key = _avatar_key(user)
    await object_store.put_object(
        bucket=settings.minio_bucket_avatars,
        key=key,
        body=normalised,
        content_type=_AVATAR_CONTENT_TYPE,
    )

    display_url = _resolve_avatar_display_url(key)
    # Even without a CDN, set the column so the SPA knows an avatar exists
    # — we encode the storage key prefixed with `minio:` as a sentinel that
    # tells the SPA to fetch /me/avatar/url for a presigned URL.
    persisted = display_url or f"minio:{key}"
    updated = await user_manager.update(
        UserUpdate(profile_image_url=persisted),
        user,
        safe=True,
    )
    await session.flush()
    _log.info(
        "avatar.uploaded user_id=%s key=%s bytes=%d",
        str(user.id),
        key,
        len(normalised),
    )
    return UserRead.model_validate(updated, from_attributes=True)


@router.delete("/me/avatar", response_model=UserRead)
async def delete_avatar(
    user: User = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> UserRead:
    """Remove the avatar blob from Minio and null the user column."""
    key = _avatar_key(user)
    try:
        await object_store.delete_object(
            bucket=settings.minio_bucket_avatars, key=key
        )
    except Exception as exc:  # noqa: BLE001 — log + continue; the column is the source of truth
        _log.warning(
            "avatar.delete_blob_failed user_id=%s key=%s detail=%s",
            str(user.id),
            key,
            exc,
        )

    updated = await user_manager.update(
        UserUpdate(profile_image_url=None), user, safe=True
    )
    _log.info("avatar.deleted user_id=%s", str(user.id))
    return UserRead.model_validate(updated, from_attributes=True)


@router.get("/me/avatar/url", response_model=AvatarUrlResponse)
async def avatar_url(
    user: User = Depends(current_active_user),
) -> AvatarUrlResponse:
    """Return a fresh URL for the caller's avatar.

    When a public CDN is configured the URL is stable; otherwise the URL is
    a 1-hour presigned GET against Minio. Either way the SPA can swap it
    directly into ``<img src>``.
    """
    if not user.profile_image_url:
        raise HTTPException(status_code=404, detail="NO_AVATAR")

    key = _avatar_key(user)
    public = object_store.public_url_for(key)
    if public is not None:
        return AvatarUrlResponse(url=public, expires_in=0)

    expires = 3600
    url = await object_store.presigned_get_url(
        bucket=settings.minio_bucket_avatars,
        key=key,
        expires_in=expires,
    )
    return AvatarUrlResponse(url=url, expires_in=expires)
