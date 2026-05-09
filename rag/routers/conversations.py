"""Conversation history CRUD."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import DB_PATH, new_id, now_iso
from routers.deps import require_auth

router = APIRouter(tags=["conversations"], dependencies=[Depends(require_auth)])


class CreateConversation(BaseModel):
    title: str


@router.get("/conversations")
async def list_conversations() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT 100
            """
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("/conversations", status_code=201)
async def create_conversation(body: CreateConversation) -> dict:
    cid = new_id()
    ts = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, body.title[:120], ts, ts),
        )
        await db.commit()
    return {"id": cid}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            "SELECT id, title, created_at FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        conv = await cur.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        cur = await db.execute(
            "SELECT id, role, content, sources, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        )
        messages = await cur.fetchall()

    return {**dict(conv), "messages": [dict(m) for m in messages]}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        await db.commit()
