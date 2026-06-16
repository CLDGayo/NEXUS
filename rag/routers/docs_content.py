"""Serve documentation markdown files from the repo-level docs/ directory."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["docs"])

DOCS_ROOT = Path(__file__).parent.parent.parent / "docs"


@router.get("/api/docs/{path:path}", response_class=PlainTextResponse)
async def get_doc(path: str) -> str:
    candidate = (DOCS_ROOT / path).resolve()
    # Guard against path traversal outside docs/
    if DOCS_ROOT.resolve() not in candidate.parents and candidate != DOCS_ROOT.resolve():
        raise HTTPException(status_code=403, detail="Forbidden")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Doc not found")
    if candidate.suffix != ".md":
        raise HTTPException(status_code=400, detail="Only .md files served")
    return candidate.read_text(encoding="utf-8")
