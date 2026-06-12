"""Phase 49 — Prompt Studio HTTP surface for per-tenant ``ai_settings``.

Exposes the read/write API behind the Settings → AI Studio page:

    GET  /api/workspace/ai-settings   -> full merged blob (defaults filled)
    PUT  /api/workspace/ai-settings   -> partial update, merged + persisted

Both endpoints are gated by ``require_manager`` (Phase 50 RBAC) so workspace
owners and admins can read or mutate the persona / node-toggle / model-param
configuration; plain members are rejected. The write path reuses ``ai_settings`` engine helpers
(``merged_ai_settings`` for shape normalization, ``model_choice_allowlist``
for the model id allowlist) so the HTTP layer never re-derives bounds.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session
from rag.database.models import Tenant
from rag.orchestrator.ai_settings import (
    merged_ai_settings,
    model_choice_allowlist,
)
from routers.deps import require_manager

router = APIRouter(tags=["workspace-ai-settings"])

# Soft cap on scenario prompt length — keeps a single tenant from stuffing a
# multi-megabyte blob into the JSONB column / LLM system prompt.
_PROMPT_MAX_LEN = 8000


class ScenarioPromptsPatch(BaseModel):
    introduction: str | None = Field(default=None, max_length=_PROMPT_MAX_LEN)
    core_behavior: str | None = Field(default=None, max_length=_PROMPT_MAX_LEN)
    checkout_transition: str | None = Field(
        default=None, max_length=_PROMPT_MAX_LEN
    )
    human_handoff: str | None = Field(default=None, max_length=_PROMPT_MAX_LEN)


class ActiveNodesPatch(BaseModel):
    sentiment_analysis: bool | None = None
    research_mode: bool | None = None
    inject_product_context: bool | None = None
    build_carousel: bool | None = None
    sdr_persona: bool | None = None
    hitl_handover: bool | None = None


class ModelParamsPatch(BaseModel):
    # Hard bounds enforced here (early 422) AND by resolve_model_params at
    # read time (silent fallback). model_choice allowlist is checked in the
    # handler since it depends on runtime settings.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=8192)
    model_choice: str | None = None


class AiSettingsPut(BaseModel):
    """Partial update body. Any omitted key/sub-key is left untouched."""

    scenario_prompts: ScenarioPromptsPatch | None = None
    active_nodes: ActiveNodesPatch | None = None
    model_params: ModelParamsPatch | None = None


def _deep_merge_over(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge *incoming* over *base*, one level deep (the ai_settings shape).

    Sub-dicts are merged key-by-key so a partial ``model_params`` update does
    not clobber the untouched siblings; scalars overwrite.
    """
    result = dict(base)
    for key, val in incoming.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **val}
        else:
            result[key] = val
    return result


def _with_meta(merged: dict[str, Any]) -> dict[str, Any]:
    """Attach response-only metadata (the model_choice allowlist) so the
    Prompt Studio Select can render its options without a second request.
    ``available_models`` is response-only — PUT bodies ignore unknown keys."""
    return {**merged, "available_models": sorted(model_choice_allowlist())}


@router.get("/ai-settings")
async def get_ai_settings(
    tenant: Tenant = Depends(require_manager),
) -> dict[str, Any]:
    """Return the tenant's fully-merged ai_settings (every field populated)."""
    return _with_meta(merged_ai_settings(tenant.ai_settings))


@router.put("/ai-settings")
async def put_ai_settings(
    body: AiSettingsPut,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Apply a partial update, validate bounds, persist, return the merged blob."""
    # Only the keys/sub-keys the client actually sent.
    incoming = body.model_dump(exclude_unset=True, exclude_none=True)

    current = merged_ai_settings(tenant.ai_settings)
    merged = merged_ai_settings(_deep_merge_over(current, incoming))

    # model_choice allowlist — Pydantic can't express it (depends on runtime
    # settings), so reject explicitly with a 400 the UI can surface.
    choice = (merged.get("model_params") or {}).get("model_choice")
    if choice is not None and choice not in model_choice_allowlist():
        raise HTTPException(
            status_code=400,
            detail=(
                f"model_choice {choice!r} not allowed. "
                f"Valid: {sorted(model_choice_allowlist())}"
            ),
        )

    tenant.ai_settings = merged
    await db.commit()
    return _with_meta(merged)
