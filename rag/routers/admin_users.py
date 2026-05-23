"""Phase 28 Part 1 — superuser-only user provisioning surface.

All routes guarded by ``current_superuser``; non-superuser callers receive
401/403 from fastapi-users' default. Mount at ``/api/admin`` in ``rag.main``.

Routes:
    GET    /api/admin/users          — paginated list (q=, limit, offset)
    POST   /api/admin/users          — create user (optionally superuser)
    POST   /api/admin/users/{id}/promote
    POST   /api/admin/users/{id}/demote
    DELETE /api/admin/users/{id}     — soft delete (is_active=false) by default,
                                       hard delete with ?hard=true
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.exceptions import UserAlreadyExists
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_superuser
from rag.auth.db import get_user_db
from rag.auth.manager import UserManager, get_user_manager
from rag.auth.schemas import UserCreate, UserRead
from rag.database.engine import get_async_session
from rag.database.models import User

_log = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)
    is_superuser: bool = False


class AdminUserListResponse(BaseModel):
    items: list[UserRead]
    total: int
    limit: int
    offset: int


async def _count_active_superusers(session: AsyncSession) -> int:
    """Return the number of active superusers (``is_active=true``).

    SQLAlchemy 2.0 ``Mapped[bool]`` carries column ops at runtime but mypy
    strict (no SQLA plugin) sees the equality as a plain bool — the inline
    type ignores below acknowledge that gap without disabling the gate.
    """
    stmt = (
        select(func.count())
        .select_from(User)
        .where(
            User.is_superuser.is_(True),  # type: ignore[attr-defined]
            User.is_active.is_(True),  # type: ignore[attr-defined]
        )
    )
    result = await session.execute(stmt)
    count = result.scalar_one_or_none()
    return int(count or 0)


async def _load_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    return target


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    q: str | None = Query(default=None, description="email substring filter"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
) -> AdminUserListResponse:
    base = select(User)
    count_base = select(func.count()).select_from(User)
    if q:
        like = f"%{q.lower()}%"
        base = base.where(func.lower(User.email).like(like))
        count_base = count_base.where(func.lower(User.email).like(like))

    rows = (
        await session.execute(
            base.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    total = (await session.execute(count_base)).scalar_one_or_none() or 0

    return AdminUserListResponse(
        items=[UserRead.model_validate(u, from_attributes=True) for u in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(
    body: AdminUserCreate,
    admin: User = Depends(current_superuser),
    user_manager: UserManager = Depends(get_user_manager),
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
) -> UserRead:
    try:
        created = await user_manager.create(
            UserCreate(
                email=body.email,
                password=body.password,
                display_name=body.display_name,
            ),
            safe=False,
        )
    except UserAlreadyExists:
        raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED")

    if body.is_superuser:
        created = await user_db.update(created, {"is_superuser": True})

    _log.info(
        "admin.user_created actor=%s target=%s superuser=%s",
        str(admin.id),
        str(created.id),
        body.is_superuser,
    )
    return UserRead.model_validate(created, from_attributes=True)


@router.post("/users/{user_id}/promote", response_model=UserRead)
async def promote_user(
    user_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
) -> UserRead:
    target = await _load_user(session, user_id)
    if target.is_superuser:
        return UserRead.model_validate(target, from_attributes=True)
    updated = await user_db.update(target, {"is_superuser": True})
    _log.info(
        "admin.user_promoted actor=%s target=%s", str(admin.id), str(updated.id)
    )
    return UserRead.model_validate(updated, from_attributes=True)


@router.post("/users/{user_id}/demote", response_model=UserRead)
async def demote_user(
    user_id: uuid.UUID,
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
) -> UserRead:
    if admin.id == user_id:
        raise HTTPException(status_code=409, detail="CANNOT_DEMOTE_SELF")
    target = await _load_user(session, user_id)
    if not target.is_superuser:
        return UserRead.model_validate(target, from_attributes=True)
    if await _count_active_superusers(session) <= 1:
        raise HTTPException(status_code=409, detail="LAST_SUPERUSER")
    updated = await user_db.update(target, {"is_superuser": False})
    _log.info(
        "admin.user_demoted actor=%s target=%s", str(admin.id), str(updated.id)
    )
    return UserRead.model_validate(updated, from_attributes=True)


@router.delete("/users/{user_id}", response_model=UserRead | None)
async def delete_user(
    user_id: uuid.UUID,
    hard: bool = Query(default=False, description="true = hard delete row"),
    admin: User = Depends(current_superuser),
    session: AsyncSession = Depends(get_async_session),
    user_manager: UserManager = Depends(get_user_manager),
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
) -> UserRead | None:
    if admin.id == user_id:
        raise HTTPException(status_code=409, detail="CANNOT_DELETE_SELF")
    target = await _load_user(session, user_id)
    if target.is_superuser and await _count_active_superusers(session) <= 1:
        raise HTTPException(status_code=409, detail="LAST_SUPERUSER")

    if hard:
        await user_manager.delete(target)
        _log.info(
            "admin.user_deleted actor=%s target=%s mode=hard",
            str(admin.id),
            str(user_id),
        )
        return None

    updated = await user_db.update(target, {"is_active": False})
    _log.info(
        "admin.user_deleted actor=%s target=%s mode=soft",
        str(admin.id),
        str(user_id),
    )
    return UserRead.model_validate(updated, from_attributes=True)
