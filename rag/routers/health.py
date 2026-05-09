"""Health check — Qdrant + Groq status."""

import os

from fastapi import APIRouter
from qdrant_client import AsyncQdrantClient

router = APIRouter(tags=["health"])

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")


@router.get("/health")
async def health() -> dict:
    qdrant_ok = False
    try:
        client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=3)
        await client.get_collection(COLLECTION)
        await client.close()
        qdrant_ok = True
    except Exception:
        pass

    groq_ok = bool(os.environ.get("GROQ_API_KEY"))
    status = "ok" if (qdrant_ok and groq_ok) else "degraded"
    return {"status": status, "qdrant": qdrant_ok, "groq_key": groq_ok}
