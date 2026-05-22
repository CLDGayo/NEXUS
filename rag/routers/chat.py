"""Chat endpoint — SSE streaming over POST.

Phase 9: `/api/chat/stream` now dispatches the question to the v2 LangGraph
orchestrator (``rag.orchestrator.graph.run_graph``) instead of the legacy
linear pipeline (``rag.query.stream_answer``). The SSE wire format the SPA
consumes is unchanged — node lifecycle events emitted by ``astream_events``
are mapped onto the v1 ``status / sources / token / followups`` shape.

The LangGraph generate node is not yet token-streaming (LiteLLM
non-streaming today), so the assistant message arrives as a single
``token`` event. Follow-ups still go through the cheap secondary Groq call
in ``rag.query.generate_followups`` after the graph terminates.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import settings_service
from app_logger import logger
from database import DB_PATH, new_id, now_iso
from events import bus
from query import display_name, generate_followups
from resources_store import load_active_system_prompt

from rag.auth import current_active_user
from rag.database.engine import get_async_session
from rag.database.models import ChatSession, User
from rag.retrieval.types import ScoredChunk

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    history: list[dict] = []
    # Phase 15 — multimodal: list of {type:"image", url:"data:..."} items.
    attachments: list[dict] | None = None


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    question: str
    answer: str
    rating: str  # "up" | "down"


def _chunks_to_v1_sources(chunks: list[ScoredChunk]) -> list[dict]:
    """Project v2 ``ScoredChunk`` list onto the v1 ``DocumentSource`` shape
    the SPA renders: ``{index, file, display, chunks:[{heading,score,text}]}``.

    Chunks from the same source file are merged so the citation panel shows
    one card per note, matching v1 behaviour.
    """

    by_file: dict[str, dict] = {}
    order: list[str] = []
    for chunk in chunks:
        meta = chunk.metadata or {}
        file_path = str(meta.get("file") or meta.get("path") or chunk.id)
        if file_path not in by_file:
            by_file[file_path] = {
                "index": len(order) + 1,
                "file": file_path,
                "display": meta.get("title") or display_name(file_path),
                "chunks": [],
            }
            order.append(file_path)
        by_file[file_path]["chunks"].append(
            {
                "heading": meta.get("heading", ""),
                "score": round(float(chunk.score), 3),
                "text": chunk.text,
            }
        )
    return [by_file[f] for f in order]


async def _resolve_session(
    db: AsyncSession,
    user: User,
    session_id: str | None,
) -> str:
    """Phase 27 — bind every chat turn to ``app.chat_sessions``.

    * If the client passes a session_id, the row must exist and be owned by
      the authenticated user. Foreign sessions return 403; unknown ones 404.
    * If no session_id is given, mint a new server-side UUID v4 and persist
      a chat_sessions row owned by the user before returning it.

    The returned string is what we pass to LangGraph as ``thread_id``.
    """
    if session_id:
        row = await db.get(ChatSession, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="session not owned")
        # ``last_used_at`` advances automatically via the ``onupdate`` server
        # default; force a no-op write so the timestamp moves.
        row.title = row.title
        await db.commit()
        return row.session_id

    new_id_str = str(uuid.uuid4())
    db.add(ChatSession(session_id=new_id_str, user_id=user.id))
    await db.commit()
    return new_id_str


async def _stream_graph_events(
    question: str,
    thread_key: str,
    user_id: str,
    system_prompt: str | None,  # accepted for parity; surface-aware prompt
    # selection lives inside the graph (rag/orchestrator/nodes.py).
    attachments: list[dict] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the LangGraph orchestrator and translate node lifecycle events
    into the v1 SSE payload shape (``status / sources / token / followups``).

    ``thread_key`` is pre-resolved by ``_resolve_session()`` against the
    ``app.chat_sessions`` ownership table — callers must NOT pass a raw
    client-supplied session_id here.

    Yields the captured final answer + sources at the end via a synthetic
    ``__final__`` event so the caller can persist the exchange.
    """

    correlation_id = str(uuid.uuid4())
    state: dict[str, Any] = {
        "query": question,
        "thread_key": thread_key,
        "correlation_id": correlation_id,
        "surface": "spa",
    }
    if attachments:
        state["attachments"] = attachments
    config = {"configurable": {"thread_id": thread_key, "user_id": user_id}}

    yield {"type": "status", "stage": "searching"}

    searching_announced = True
    retrieved_announced = False
    generating_announced = False
    final_answer = ""
    final_sources: list[dict] = []

    # Deferred import: ``rag.orchestrator.graph`` transitively imports
    # ``rag.retrieval.dense`` (fastembed), which is only installed in the
    # ingest-heavy runtime image. Tests that exercise non-chat routes must
    # be able to import ``rag.routers.chat`` without it.
    from rag.orchestrator.graph import get_graph

    graph = get_graph()
    async for event in graph.astream_events(state, config=config, version="v2"):
        ev_type = event.get("event")
        name = event.get("name")
        data = event.get("data") or {}

        if ev_type == "on_chain_end" and name == "rerank":
            output = data.get("output") or {}
            reranked = output.get("reranked") or []
            final_sources = _chunks_to_v1_sources(reranked)
            yield {"type": "sources", "items": final_sources}
            if not retrieved_announced:
                yield {
                    "type": "status",
                    "stage": "retrieved",
                    "count": len(final_sources),
                }
                retrieved_announced = True

        elif ev_type == "on_chain_start" and name == "generate":
            if not generating_announced:
                yield {"type": "status", "stage": "generating"}
                generating_announced = True

        elif ev_type == "on_chain_end" and name == "generate":
            output = data.get("output") or {}
            answer = (output.get("answer") or "").strip()
            if answer:
                final_answer = answer
                # Today's generate node is non-streaming — emit the whole
                # answer as a single token chunk so the SPA renders it.
                yield {"type": "token", "content": answer}

        elif ev_type == "on_chain_end" and name in {"respond", "abstain"}:
            output = data.get("output") or {}
            answer = (output.get("answer") or "").strip()
            if answer and answer != final_answer:
                # Phase 25.1 — guardrails may swap state["answer"] (e.g.
                # generate emitted empty content and abstain_node wrote
                # handover_fallback_text). Emit that as a token so the
                # SPA actually renders the message body instead of just
                # the citations strip (the "ghost query" bug).
                yield {"type": "token", "content": answer}
                final_answer = answer

    if not searching_announced:
        # Defensive — graph emitted no events (should not happen).
        yield {"type": "status", "stage": "searching"}

    # Follow-up suggestions: cheap secondary Groq call. Never raises.
    followups = await generate_followups(question, final_answer)
    if followups:
        yield {"type": "followups", "items": followups}

    # Sentinel for the outer generator to capture for persistence.
    yield {
        "type": "__final__",
        "answer": final_answer,
        "sources": final_sources,
    }


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    # Phase 27 — bind the turn to an owned session BEFORE LangGraph runs.
    thread_key = await _resolve_session(db, user, body.session_id)
    user_id = str(user.id)

    # Settings reads kept for SPA compatibility (UI may surface the chosen
    # models even though the graph itself reads from rag.config.settings).
    await settings_service.get("TOP_K")
    await settings_service.get("GROQ_MODEL")
    await settings_service.get("FOLLOWUP_MODEL")
    system_prompt = await load_active_system_prompt()

    async def generate():
        full_response = ""
        sources_data: list[dict] = []
        t0 = time.time()

        logger.info(
            f"Chat query user={user_id} thread={thread_key} "
            f"q={body.question[:80]!r}"
        )

        try:
            async for event in _stream_graph_events(
                body.question,
                thread_key,
                user_id,
                system_prompt,
                attachments=body.attachments,
            ):
                etype = event.get("type")
                if etype == "__final__":
                    full_response = event.get("answer", "")
                    sources_data = event.get("sources", [])
                    continue
                yield f"data: {json.dumps(event)}\n\n"

            logger.info(f"Sources used: {len(sources_data)}")

        except Exception as exc:
            logger.error(f"Stream error: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            await bus.publish(
                "chat.error",
                {"session_id": thread_key, "user_id": user_id, "error": str(exc)},
            )

        yield "data: [DONE]\n\n"

        if full_response:
            await _save_exchange(
                thread_key,
                body.question,
                full_response,
                sources_data,
            )

        await bus.publish(
            "chat.complete",
            {
                "session_id": thread_key,
                "user_id": user_id,
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


@router.post("/feedback")
async def chat_feedback(
    body: FeedbackRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """Log a rating and publish a chat.feedback.{up,down} event.

    Phase 27 — the optional ``session_id`` must exist and belong to the
    caller. If absent, feedback is recorded as user-scoped only.
    """
    if body.rating not in {"up", "down"}:
        return {"ok": False, "error": "rating must be 'up' or 'down'"}

    if body.session_id is not None:
        row = await db.get(ChatSession, body.session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="session not owned")

    logger.info(
        f"Chat feedback: user={user.id} rating={body.rating} "
        f"session={body.session_id} q={body.question[:60]!r}"
    )
    await bus.publish(
        f"chat.feedback.{body.rating}",
        {
            "session_id": body.session_id,
            "user_id": str(user.id),
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
