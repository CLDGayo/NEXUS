"""Conversation history CRUD.

Phase 30.1 — every read/write goes through the SQLAlchemy 2.0 async ORM
against ``app.conversations`` / ``app.messages``. Path params are typed
``uuid.UUID`` so the framework rejects malformed ids with a 422 before
the handler runs.

Tenant + user guard order:
    * ``current_active_user`` resolves the fastapi-users JWT;
    * ``get_current_tenant`` validates membership via ``app.tenant_users``;
    * every ``select(...)`` carries
      ``.where(Conversation.user_id == user.id,
              Conversation.tenant_id == tenant.id)``
      so the same JWT used against two different workspaces (different
      ``X-Tenant-ID``) yields disjoint result sets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.auth import current_active_user, get_current_tenant
from rag.database.engine import get_async_session
from rag.database.models import Conversation, Message, Tenant, User

router = APIRouter(tags=["conversations"])


class CreateConversation(BaseModel):
    title: str


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            Conversation.updated_at,
            func.count(Message.id).label("message_count"),
        )
        .select_from(Conversation)
        .outerjoin(
            Message,
            (Message.conversation_id == Conversation.id)
            & (Message.tenant_id == tenant.id),
        )
        .where(
            Conversation.user_id == user.id,
            Conversation.tenant_id == tenant.id,
        )
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "message_count": int(row.message_count or 0),
        }
        for row in result.all()
    ]


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: CreateConversation,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    conv = Conversation(
        id=uuid.uuid4(),
        title=body.title[:120],
        user_id=user.id,
        tenant_id=tenant.id,
    )
    db.add(conv)
    await db.commit()
    return {"id": str(conv.id)}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
        Conversation.tenant_id == tenant.id,
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if conv is None:
        # Don't disclose existence to non-owners.
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant.id,
        )
        .order_by(Message.created_at.asc())
    )
    messages = (await db.execute(msg_stmt)).scalars().all()
    return {
        "id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    response_class=Response,
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(current_active_user),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    stmt = (
        delete(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.tenant_id == tenant.id,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return Response(status_code=204)


# Phase 30.1 — exposed for tests that touch the (timezone-aware) updated_at
# column directly; keeps the route handlers free of datetime fiddling.
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
