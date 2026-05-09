"""Application log viewer."""

from fastapi import APIRouter, Depends

from app_logger import get_log_entries
from routers.deps import require_auth

router = APIRouter(tags=["logs"], dependencies=[Depends(require_auth)])


@router.get("/logs")
async def get_logs() -> dict:
    entries = get_log_entries()
    return {"entries": list(reversed(entries))}
