"""Dashboard observability endpoint — vault, Qdrant, Groq, charts, activity."""

import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from qdrant_client import AsyncQdrantClient

from routers.deps import require_auth

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_auth)])

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
VAULT_PATH = os.environ.get("VAULT_PATH", "")
RAG_DIR = Path(__file__).parent.parent

_SKIP = {".obsidian", "_publish", "rag", ".git", "node_modules"}
INBOX_FOLDER = "00 - Inbox"

TUNNEL_HINT = "ssh -L 6333:127.0.0.1:6333 root@72.62.196.231 -N -f"
GROQ_MODEL = "llama-3.3-70b-versatile"


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
        return getattr(info, "points_count", None) or getattr(info, "vectors_count", None) or 0
    except Exception:
        return 0


def _mock_charts() -> dict:
    rng = random.Random(42)
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    query_volume = [
        {"date": d.isoformat(), "queries": rng.randint(8, 38)} for d in days
    ]
    ingestion = [
        {"date": d.isoformat(), "chunks": rng.randint(0, 120)} for d in days
    ]
    return {"query_volume": query_volume, "ingestion": ingestion}


def _mock_recent_activity() -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = [
        ("Theme-Aware CSS Variables.md", "06 - Concepts", "Indexed", 12),
        ("2026-05-09.md", "05 - Daily Notes", "Indexed", 47),
        ("GSAP Puppeteer Verification Workaround.md", "06 - Concepts", "Indexed", 124),
        ("Quick capture — pricing idea.md", "00 - Inbox", "Pending", 210),
        ("NEXUS RAG Roadmap.md", "01 - Projects", "Indexed", 360),
        ("Anthropic.md", "07 - Entities", "Indexed", 1440),
    ]
    return [
        {
            "timestamp": (now - timedelta(minutes=mins)).isoformat(),
            "file": file,
            "folder": folder,
            "status": status,
        }
        for (file, folder, status, mins) in rows
    ]


@router.get("/stats")
async def stats() -> dict:
    qdrant_ok = await _ping_qdrant()
    total_chunks = await _qdrant_chunk_count() if qdrant_ok else 0
    groq_ok = bool(os.environ.get("GROQ_API_KEY"))

    return {
        "kpis": {
            "total_notes": _count_notes(),
            "total_chunks": total_chunks,
            "pending_inbox": _count_inbox(),
            "avg_retrieval_latency_s": 0.85,
        },
        "health": {
            "qdrant": {
                "ok": qdrant_ok,
                "hint": None if qdrant_ok else TUNNEL_HINT,
            },
            "groq": {"ok": groq_ok},
            "watcher": {"ok": True},
        },
        "groq_usage": {
            "tokens_30d": 1_482_500,
            "estimated_cost_usd": 11.86,
            "model": GROQ_MODEL,
        },
        "charts": _mock_charts(),
        "recent_activity": _mock_recent_activity(),
        "last_indexed": _last_indexed(),
    }
