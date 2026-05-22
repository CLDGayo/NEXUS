"""SQLAlchemy ORM models for the ``app`` Postgres schema.

Phase 27 Part 1 ships three tables:
    * ``app.users`` — fastapi-users default columns + display_name + profile_image_url.
    * ``app.access_token`` — reserved for fastapi-users' ``DatabaseStrategy``;
      we use ``JWTStrategy`` today (stateless), but ship the table now so
      Part 2 can flip without a migration.
    * ``app.chat_sessions`` — server-issued session_id PK, FK to users.id.
      Every chat turn looks up this row to enforce tenant ownership before
      LangGraph is invoked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from rag.database.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    __tablename__ = "access_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"), nullable=False
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app.users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
