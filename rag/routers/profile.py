"""Phase 28 Part 1 — authenticated user self-service profile router.

Currently ships ``POST /api/users/me/password`` which requires the caller to
prove ownership of the existing password before the new one is accepted. The
built-in ``PATCH /api/users/me`` from fastapi-users does NOT enforce that
check (it lets any holder of a valid JWT rotate the password), so the SPA
profile page calls this endpoint instead. ``PATCH /api/users/me`` remains
available for non-credential mutations (display_name, profile_image_url).

Avatar uploads land in Phase 28 Part 2 (Minio-backed).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from rag.auth import current_active_user
from rag.auth.manager import UserManager, get_user_manager
from rag.auth.schemas import UserUpdate
from rag.database.models import User

_log = logging.getLogger(__name__)

router = APIRouter(tags=["profile"])


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=256)


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
