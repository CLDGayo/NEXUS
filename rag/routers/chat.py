"""Chat endpoint — SSE streaming over POST."""

import json
import time

import aiosqlite
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import settings_service
from app_logger import logger
from database import DB_PATH, new_id, now_iso
from events import bus
from query import stream_answer
from resources_store import load_active_system_prompt
from routers.deps import require_auth_or_token

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    history: list[dict] = []


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    question: str
    answer: str
    rating: str  # "up" | "down"


@router.post("/stream", dependencies=[Depends(require_auth_or_token("chat:read"))])
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    top_k = await settings_service.get("TOP_K")
    groq_model = await settings_service.get("GROQ_MODEL")
    followup_model = await settings_service.get("FOLLOWUP_MODEL")
    system_prompt = await load_active_system_prompt()

    async def generate():
        full_response = ""
        sources_data: list[dict] = []
        t0 = time.time()

        logger.info(f"Chat query: {body.question[:80]!r}")

        try:
            async for event in stream_answer(
                body.question,
                body.history,
                top_k=top_k,
                groq_model=groq_model,
                followup_model=followup_model,
                system_prompt=system_prompt,
            ):
                etype = event.get("type")
                if etype == "sources":
                    sources_data = event.get("items", [])
                elif etype == "token":
                    full_response += event.get("content", "")
                yield f"data: {json.dumps(event)}\n\n"

            logger.info(f"Sources used: {len(sources_data)}")

        except Exception as exc:
            logger.error(f"Stream error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            await bus.publish(
                "chat.error",
                {"session_id": body.session_id, "error": str(exc)},
            )

        yield "data: [DONE]\n\n"

        if body.session_id and full_response:
            await _save_exchange(
                body.session_id,
                body.question,
                full_response,
                sources_data,
            )

        await bus.publish(
            "chat.complete",
            {
                "session_id": body.session_id,
                "question": body.question[:200],
                "latency_ms": int((time.time() - t0) * 1000),
                "source_count": len(sources_data),
            },
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", dependencies=[Depends(require_auth_or_token("chat:write"))])
async def chat_feedback(body: FeedbackRequest) -> dict:
    """Log a rating and publish a chat.feedback.{up,down} event."""
    if body.rating not in {"up", "down"}:
        return {"ok": False, "error": "rating must be 'up' or 'down'"}
    logger.info(
        f"Chat feedback: rating={body.rating} session={body.session_id} "
        f"q={body.question[:60]!r}"
    )
    await bus.publish(
        f"chat.feedback.{body.rating}",
        {
            "session_id": body.session_id,
            "question": body.question[:200],
            "answer": body.answer[:500],
        },
    )
    return {"ok": True}


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
