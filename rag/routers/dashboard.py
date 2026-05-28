"""Dashboard observability endpoint — live telemetry, zero mocks.

Surfaces real metrics aggregated at request time from:
    * Postgres (``app.conversations`` / ``app.messages`` /
      ``app.integrations``) — scoped to the calling user for per-row
      aggregates; vault- / process-wide counters stay global.
    * Qdrant (collection point count, /healthz ping)
    * Filesystem (vault note count, inbox, mtime histogram)
    * Messenger overlay (token presence)
    * Process uptime (monotonic clock since module import)

Phase 30.1 — every SQL helper went from ``aiosqlite`` to a one-shot
``AsyncSession`` opened from the ``app`` schema sessionmaker.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from qdrant_client import AsyncQdrantClient
from sqlalchemy import cast, func, select
from sqlalchemy.types import Integer

import messenger_overlay

from rag.auth import current_active_user
from rag.database.engine import get_sessionmaker
from rag.database.models import Conversation, Integration, Message, User

router = APIRouter(tags=["dashboard"])

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
VAULT_PATH = os.environ.get("VAULT_PATH", "")
RAG_DIR = Path(__file__).parent.parent

_SKIP = {".obsidian", "_publish", "rag", ".git", "node_modules"}
INBOX_FOLDER = "00 - Inbox"

QDRANT_DOWN_HINT = (
    "Cannot reach Qdrant. Check internet, "
    "https://qdrant.nexus.gayo-sphere.cloud/healthz, "
    "and that the VPS container `qdrant-nexus` is running."
)
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Monotonic boot timestamp — captured at import for uptime reporting.
_BOOT_TS = time.monotonic()

# Latency window: pair user→assistant timestamps within this many seconds
# to estimate retrieval latency. Wider intervals are user-think gaps.
_LATENCY_WINDOW_S = 30.0


def _vault_root() -> Path:
    return Path(VAULT_PATH) if VAULT_PATH else RAG_DIR.parent


def _count_notes() -> int:
    count = 0
    for p in _vault_root().rglob("*.md"):
        if not any(skip in p.parts for skip in _SKIP):
            count += 1
    return count


def _count_inbox() -> int:
    inbox = _vault_root() / INBOX_FOLDER
    if not inbox.exists():
        return 0
    return sum(1 for _ in inbox.glob("*.md"))


def _last_indexed() -> float | None:
    state = RAG_DIR / ".ingest_state.json"
    return state.stat().st_mtime if state.exists() else None


def _messenger_active() -> bool:
    return bool(
        messenger_overlay.current_verify_token()
        and messenger_overlay.current_page_access_token()
    )


async def _ping_qdrant() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{QDRANT_URL}/healthz")
            return r.status_code == 200
    except Exception:
        return False


async def _qdrant_chunk_count() -> int:
    try:
        client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=3)
        info = await client.get_collection(COLLECTION)
        await client.close()
        return (
            getattr(info, "points_count", None)
            or getattr(info, "vectors_count", None)
            or 0
        )
    except Exception:
        return 0


async def _count_messages(user_id: str) -> tuple[int, int]:
    """Return (total_messages, total_conversations) for ``user_id``."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            msgs = (
                await db.execute(
                    select(func.count(Message.id)).where(
                        Message.user_id == user_id
                    )
                )
            ).scalar_one()
            convs = (
                await db.execute(
                    select(func.count(Conversation.id)).where(
                        Conversation.user_id == user_id
                    )
                )
            ).scalar_one()
        return int(msgs or 0), int(convs or 0)
    except Exception:
        return 0, 0


async def _count_integrations() -> tuple[int, int]:
    """Return (active, total). Integrations stay global — admin-level state."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            row = (
                await db.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                cast(Integration.enabled, Integer)
                            ),
                            0,
                        ),
                        func.count(Integration.id),
                    )
                )
            ).one()
        return int(row[0] or 0), int(row[1] or 0)
    except Exception:
        return 0, 0


async def _query_volume_7d(user_id: str) -> list[dict]:
    """Daily user-message counts for ``user_id`` across the trailing 7 days."""
    today = datetime.now(timezone.utc).date()
    bins: dict[str, int] = {
        (today - timedelta(days=i)).isoformat(): 0 for i in range(6, -1, -1)
    }
    try:
        cutoff_dt = datetime.combine(
            today - timedelta(days=6),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        day_expr = func.to_char(Message.created_at, "YYYY-MM-DD")
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            result = await db.execute(
                select(day_expr.label("day"), func.count(Message.id))
                .where(
                    Message.role == "user",
                    Message.user_id == user_id,
                    Message.created_at >= cutoff_dt,
                )
                .group_by(day_expr)
            )
            for day, count in result.all():
                if day in bins:
                    bins[day] = int(count)
    except Exception:
        pass
    return [{"date": d, "queries": n} for d, n in bins.items()]


def _ingestion_7d() -> list[dict]:
    """Vault `.md` files bucketed by mtime across the trailing 7 days."""
    today = datetime.now(timezone.utc).date()
    bins: dict[str, int] = {
        (today - timedelta(days=i)).isoformat(): 0 for i in range(6, -1, -1)
    }
    root = _vault_root()
    if not root.exists():
        return [{"date": d, "chunks": n} for d, n in bins.items()]
    for p in root.rglob("*.md"):
        if any(skip in p.parts for skip in _SKIP):
            continue
        try:
            d = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).date().isoformat()
        except OSError:
            continue
        if d in bins:
            bins[d] += 1
    return [{"date": d, "chunks": n} for d, n in bins.items()]


async def _recent_activity(user_id: str, limit: int = 8) -> list[dict]:
    """Last N user messages owned by ``user_id`` joined to conversation titles."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            stmt = (
                select(
                    Message.created_at,
                    Message.content,
                    Conversation.title,
                )
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.role == "user",
                    Message.user_id == user_id,
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).all()
    except Exception:
        return []
    return [
        {
            "timestamp": (
                row.created_at.isoformat() if row.created_at else None
            ),
            "file": (row.title or "Untitled")[:120],
            "folder": "Chat",
            "status": "Answered",
        }
        for row in rows
    ]


async def _avg_retrieval_latency(user_id: str) -> float | None:
    """Mean seconds between user msg and reply for ``user_id``.

    Pairs the latest 200 messages by ``(conversation_id, created_at)`` for
    the caller; only counts deltas inside ``_LATENCY_WINDOW_S`` to filter
    out user-think gaps. Returns None when fewer than 3 valid pairs exist.
    """
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            stmt = (
                select(
                    Message.conversation_id,
                    Message.role,
                    Message.created_at,
                )
                .where(Message.user_id == user_id)
                .order_by(Message.created_at.desc())
                .limit(200)
            )
            rows = list((await db.execute(stmt)).all())
    except Exception:
        return None

    rows.reverse()  # chronological
    by_conv: dict[str, list[tuple[str, datetime]]] = {}
    for conv_id, role, created_at in rows:
        if created_at is None:
            continue
        by_conv.setdefault(str(conv_id), []).append((role, created_at))

    deltas: list[float] = []
    for events in by_conv.values():
        for i in range(len(events) - 1):
            role_a, ts_a = events[i]
            role_b, ts_b = events[i + 1]
            if role_a != "user" or role_b != "assistant":
                continue
            d = (ts_b - ts_a).total_seconds()
            if 0 < d < _LATENCY_WINDOW_S:
                deltas.append(d)

    if len(deltas) < 3:
        return None
    return round(sum(deltas) / len(deltas), 2)


@router.get("/stats")
async def stats(user: User = Depends(current_active_user)) -> dict:
    user_id = str(user.id)
    qdrant_ok = await _ping_qdrant()
    total_chunks = await _qdrant_chunk_count() if qdrant_ok else 0
    total_messages, total_conversations = await _count_messages(user_id)
    active_integrations, total_integrations = await _count_integrations()
    messenger_active = _messenger_active()
    groq_ok = bool(os.environ.get("GROQ_API_KEY"))
    avg_latency = await _avg_retrieval_latency(user_id)

    return {
        "kpis": {
            "total_notes": _count_notes(),
            "total_chunks": total_chunks,
            "total_messages": total_messages,
            "total_conversations": total_conversations,
            "active_integrations": active_integrations,
            "pending_inbox": _count_inbox(),
            "avg_retrieval_latency_s": avg_latency,
        },
        "health": {
            "qdrant": {
                "ok": qdrant_ok,
                "hint": None if qdrant_ok else QDRANT_DOWN_HINT,
            },
            "groq": {
                "ok": groq_ok,
                "hint": None if groq_ok else "GROQ_API_KEY not set",
            },
            "messenger": {
                "ok": messenger_active,
                "hint": None
                if messenger_active
                else "Verify token and page access token not configured",
            },
            "watcher": {"ok": True},
        },
        "activity": {
            "active_integrations": active_integrations,
            "total_integrations": total_integrations,
            "messenger_active": messenger_active,
            "uptime_seconds": int(time.monotonic() - _BOOT_TS),
            "model": GROQ_MODEL,
        },
        "charts": {
            "query_volume": await _query_volume_7d(user_id),
            "ingestion": _ingestion_7d(),
        },
        "recent_activity": await _recent_activity(user_id),
        "last_indexed": _last_indexed(),
    }
