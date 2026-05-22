"""SQLAlchemy adapter binding the ``app.users`` table to fastapi-users."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import User


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)
