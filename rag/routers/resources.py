"""Resources router — prompt + template library.

Wraps `resources_store` and exposes a CRUD UI surface that activates a prompt
as the chat system prompt by writing `settings.system_prompt_id`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

import resources_store
import settings_service
from routers.deps import require_auth

router = APIRouter(tags=["resources"], dependencies=[Depends(require_auth)])


class PromptUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/prompts")
async def list_prompts() -> dict:
    items = resources_store.list_prompts()
    active = await settings_service.get("system_prompt_id") or ""
    return {"items": items, "active": active}


@router.get("/prompts/{slug}")
async def get_prompt(slug: str) -> dict:
    item = resources_store.read_prompt(slug)
    if not item:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return item


@router.put("/prompts/{slug}")
async def upsert_prompt(slug: str, body: PromptUpsert) -> dict:
    safe_slug = resources_store.slugify(slug)
    resources_store.write_prompt(safe_slug, body.name, body.body, body.metadata)
    return {"slug": safe_slug, "ok": True}


@router.delete("/prompts/{slug}", status_code=204, response_class=Response)
async def delete_prompt(slug: str) -> Response:
    if not resources_store.delete_prompt(slug):
        raise HTTPException(status_code=404, detail="Prompt not found")
    return Response(status_code=204)


@router.post("/prompts/{slug}/activate")
async def activate_prompt(slug: str) -> dict:
    if resources_store.read_prompt(slug) is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    await settings_service.set_value("system_prompt_id", slug)
    return {"active": slug}


@router.post("/prompts/deactivate")
async def deactivate_prompt() -> dict:
    await settings_service.set_value("system_prompt_id", "")
    return {"active": ""}


@router.post("/prompts/seed")
async def seed_prompts() -> dict:
    written = resources_store.seed_defaults()
    return {"written": written, "count": len(written)}
