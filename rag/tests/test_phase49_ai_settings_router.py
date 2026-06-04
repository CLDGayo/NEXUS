"""Phase 49 — Prompt Studio router (workspace_ai_settings).

Covers:
* Static lockdown — both handlers gate on ``require_owner`` (mirrors the
  Phase 31 lockdown guard so a refactor that drops the gate fails loudly).
* Pydantic bounds — temperature 0-2 and max_tokens 64-8192 reject early.
* Merge correctness — a partial PUT preserves untouched sub-keys.
* model_choice allowlist — a foreign model id is rejected with HTTP 400;
  an allowed id round-trips and is persisted.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from rag.config import settings
from rag.routers import workspace_ai_settings as mod


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakeDB:
    """Minimal AsyncSession stand-in — records whether commit was awaited."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _FakeTenant:
    def __init__(self, ai_settings: dict[str, Any] | None) -> None:
        self.ai_settings = ai_settings


# --------------------------------------------------------------------------
# Static lockdown
# --------------------------------------------------------------------------


def test_router_handlers_gate_on_require_owner() -> None:
    src = inspect.getsource(mod)
    assert "from routers.deps import require_owner" in src
    assert "Depends(require_owner)" in inspect.getsource(mod.get_ai_settings)
    assert "Depends(require_owner)" in inspect.getsource(mod.put_ai_settings)


# --------------------------------------------------------------------------
# Pydantic bounds
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_model_params_temperature_upper_bound() -> None:
    with pytest.raises(ValidationError):
        mod.ModelParamsPatch(temperature=3.0)


@pytest.mark.unit
def test_model_params_max_tokens_lower_bound() -> None:
    with pytest.raises(ValidationError):
        mod.ModelParamsPatch(max_tokens=10)


@pytest.mark.unit
def test_scenario_prompt_length_cap() -> None:
    with pytest.raises(ValidationError):
        mod.ScenarioPromptsPatch(core_behavior="x" * (mod._PROMPT_MAX_LEN + 1))


# --------------------------------------------------------------------------
# Merge correctness
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_partial_put_preserves_untouched_keys() -> None:
    tenant = _FakeTenant(
        {
            "version": 1,
            "scenario_prompts": {"core_behavior": "be kind"},
            "model_params": {"temperature": 0.5},
        }
    )
    db = _FakeDB()
    body = mod.AiSettingsPut(model_params=mod.ModelParamsPatch(max_tokens=512))

    merged = _run(mod.put_ai_settings(body=body, tenant=tenant, db=db))  # type: ignore[arg-type]

    assert db.committed is True
    # Touched sub-key applied.
    assert merged["model_params"]["max_tokens"] == 512
    # Untouched sibling preserved.
    assert merged["model_params"]["temperature"] == 0.5
    # Untouched top-level key preserved.
    assert merged["scenario_prompts"]["core_behavior"] == "be kind"
    # Response carries the response-only model allowlist.
    assert "available_models" in merged
    # Persisted blob is the pure merged settings (no response-only meta).
    assert "available_models" not in tenant.ai_settings
    assert tenant.ai_settings["model_params"]["max_tokens"] == 512


# --------------------------------------------------------------------------
# model_choice allowlist
# --------------------------------------------------------------------------


@pytest.mark.unit
def test_put_rejects_foreign_model_choice() -> None:
    from fastapi import HTTPException

    tenant = _FakeTenant(None)
    db = _FakeDB()
    body = mod.AiSettingsPut(
        model_params=mod.ModelParamsPatch(model_choice="totally-not-a-real-model")
    )

    with pytest.raises(HTTPException) as exc:
        _run(mod.put_ai_settings(body=body, tenant=tenant, db=db))  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    assert db.committed is False


@pytest.mark.unit
def test_put_accepts_allowlisted_model_choice() -> None:
    tenant = _FakeTenant(None)
    db = _FakeDB()
    body = mod.AiSettingsPut(
        model_params=mod.ModelParamsPatch(model_choice=settings.generation_model)
    )

    merged = _run(mod.put_ai_settings(body=body, tenant=tenant, db=db))  # type: ignore[arg-type]

    assert db.committed is True
    assert merged["model_params"]["model_choice"] == settings.generation_model
