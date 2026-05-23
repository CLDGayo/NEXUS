"""Conversation history CRUD.

Phase 28 Part 1 — every row is scoped to the authenticated user. The SQLite
``conversations``, ``messages`` and ``api_tokens`` tables grew a
``user_id TEXT`` column in Phase 27 Part 2; this router now requires the
fastapi-users JWT (``current_active_user``) and rejects cross-tenant reads
with a 404 (we don't disclose row existence to non-owners).
"""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from database import DB_PATH, new_id, now_iso

from rag.auth import current_active_user
from rag.database.models import User

router = APIRouter(tags=["conversations"])


class CreateConversation(BaseModel):
    title: str


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(current_active_user),
) -> list[dict]:
    user_id = str(user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.user_id = ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT 100
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: CreateConversation,
    user: User = Depends(current_active_user),
) -> dict:
    cid = new_id()
    ts = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (cid, body.title[:120], ts, ts, str(user.id)),
        )
        await db.commit()
    return {"id": cid}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
) -> dict:
    user_id = str(user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            "SELECT id, title, created_at FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conv = await cur.fetchone()
        if not conv:
            # Don't distinguish "missing" from "owned by another user".
            raise HTTPException(status_code=404, detail="Conversation not found")

        cur = await db.execute(
            "SELECT id, role, content, sources, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        )
        messages = await cur.fetchall()

    return {**dict(conv), "messages": [dict(m) for m in messages]}


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    response_class=Response,
)
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
) -> Response:
    user_id = str(user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)
