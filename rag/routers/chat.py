"""Chat endpoint — SSE streaming over POST."""

import json
import uuid

import aiosqlite
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app_logger import logger
from database import DB_PATH, now_iso, new_id
from query import stream_answer

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    history: list[dict] = []


@router.post("/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    async def generate():
        full_response = ""
        sources_data: list[dict] = []

        logger.info(f"Chat query: {body.question[:80]!r}")

        try:
            async for token, sources in stream_answer(body.question, body.history):
                if sources and not sources_data:
                    sources_data = [
                        {
                            "file": s.file,
                            "heading": s.heading,
                            "score": round(s.score, 3),
                        }
                        for s in sources
                    ]
                    yield f"data: {json.dumps({'type': 'sources', 'items': sources_data})}\n\n"
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            logger.info(f"Sources used: {len(sources_data)}")

        except Exception as exc:
            logger.error(f"Stream error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        yield "data: [DONE]\n\n"

        if body.session_id and full_response:
            await _save_exchange(
                body.session_id,
                body.question,
                full_response,
                sources_data,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _save_exchange(
    session_id: str,
    question: str,
    answer: str,
    sources: list[dict],
) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            ts = now_iso()
            title = question[:60]
            await db.execute(
                "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, ts, ts),
            )
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), session_id, "user", question, None, ts),
            )
            await db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), session_id, "assistant", answer, json.dumps(sources), ts),
            )
            await db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (ts, session_id),
            )
            await db.commit()
    except Exception as exc:
        logger.error(f"Failed to save conversation: {exc}")
