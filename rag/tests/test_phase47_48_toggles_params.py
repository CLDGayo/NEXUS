"""Phase 47/48 — Workflow Toggles & Model Params: hermetic unit tests.

All tests are @pytest.mark.unit — no network, no database, no filesystem
access beyond the module under test.

Coverage
--------
* _node_enabled (Phase 47) — default-True contract: missing key, absent
  ai_settings, empty active_nodes, explicit True/False, every default toggle.
* resolve_model_params (Phase 48) — None / default-blob fallback, valid
  override, temperature & max_tokens bounds clamping, model_choice allowlist
  enforcement, inclusive boundary values, partial overrides.
* merged_ai_settings round-trip for active_nodes / model_params sub-blobs.
"""

from __future__ import annotations

from typing import Any

import pytest

from rag.config import settings
from rag.orchestrator.ai_settings import (
    DEFAULT_AI_SETTINGS,
    _node_enabled,
    merged_ai_settings,
    resolve_model_params,
)

# Settings fallbacks the resolver must return when no valid override is present.
_DEFAULT_TRIPLE = (
    settings.generation_model,
    settings.generation_temperature,
    settings.generation_max_tokens,
)


def _state(active_nodes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal NexusState-like dict carrying *active_nodes*."""
    if active_nodes is None:
        return {}
    return {"ai_settings": {"active_nodes": active_nodes}}


def _model_params(**overrides: Any) -> dict[str, Any]:
    """Build an ai_settings blob carrying only a model_params sub-dict."""
    return {"model_params": dict(overrides)}


# ---------------------------------------------------------------------------
# Phase 47 — _node_enabled
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_node_enabled_missing_key_defaults_true() -> None:
    """A key absent from active_nodes is treated as enabled."""
    state = _state({"sentiment_analysis": True})  # sdr_persona absent
    assert _node_enabled(state, "sdr_persona") is True


@pytest.mark.unit
def test_node_enabled_explicit_false_disables() -> None:
    state = _state({"sdr_persona": False})
    assert _node_enabled(state, "sdr_persona") is False


@pytest.mark.unit
def test_node_enabled_explicit_true_enabled() -> None:
    state = _state({"sdr_persona": True})
    assert _node_enabled(state, "sdr_persona") is True


@pytest.mark.unit
def test_node_enabled_absent_ai_settings_defaults_true() -> None:
    """An empty state (no ai_settings at all) enables every node."""
    assert _node_enabled({}, "hitl_handover") is True


@pytest.mark.unit
def test_node_enabled_empty_active_nodes_defaults_true() -> None:
    """ai_settings present but no active_nodes map → enabled."""
    assert _node_enabled({"ai_settings": {}}, "build_carousel") is True


@pytest.mark.unit
def test_node_enabled_none_value_enables() -> None:
    """Only the literal ``False`` disables; ``None`` still enables."""
    state = _state({"inject_product_context": None})
    assert _node_enabled(state, "inject_product_context") is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "sentiment_analysis",
        "research_mode",
        "inject_product_context",
        "build_carousel",
        "sdr_persona",
        "hitl_handover",
    ],
)
def test_node_enabled_default_blob_all_true(key: str) -> None:
    """Every toggle in the merged default blob reports enabled."""
    state = {"ai_settings": merged_ai_settings(None)}
    assert _node_enabled(state, key) is True


@pytest.mark.unit
def test_node_enabled_one_off_does_not_affect_others() -> None:
    """Disabling one toggle leaves the rest enabled (tenant isolation)."""
    merged = merged_ai_settings({"active_nodes": {"sdr_persona": False}})
    state = {"ai_settings": merged}
    assert _node_enabled(state, "sdr_persona") is False
    assert _node_enabled(state, "build_carousel") is True
    assert _node_enabled(state, "hitl_handover") is True


# ---------------------------------------------------------------------------
# Phase 48 — resolve_model_params
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_none_falls_back_to_settings() -> None:
    """``None`` ai_settings → the settings.* default triple."""
    assert resolve_model_params(None) == _DEFAULT_TRIPLE


@pytest.mark.unit
def test_resolve_default_blob_falls_back_to_settings() -> None:
    """The default blob (all model_params None) → settings.* triple."""
    assert resolve_model_params(merged_ai_settings(None)) == _DEFAULT_TRIPLE


@pytest.mark.unit
def test_resolve_valid_override_applied() -> None:
    """A fully-valid override is applied verbatim."""
    ai = _model_params(
        temperature=1.2,
        max_tokens=2048,
        model_choice=settings.followup_model,
    )
    model, temperature, max_tokens = resolve_model_params(ai)
    assert model == settings.followup_model
    assert temperature == pytest.approx(1.2)
    assert max_tokens == 2048


@pytest.mark.unit
@pytest.mark.parametrize("bad_temp", [-0.5, 2.1, 3.5, -1, "hot", None])
def test_resolve_temperature_out_of_bounds_falls_back(bad_temp: Any) -> None:
    """Out-of-range or non-numeric temperature → settings default."""
    _, temperature, _ = resolve_model_params(_model_params(temperature=bad_temp))
    assert temperature == settings.generation_temperature


@pytest.mark.unit
@pytest.mark.parametrize("good_temp", [0.0, 2.0, 1.0])
def test_resolve_temperature_inclusive_bounds_applied(good_temp: float) -> None:
    """0.0 and 2.0 are inclusive and pass through."""
    _, temperature, _ = resolve_model_params(_model_params(temperature=good_temp))
    assert temperature == pytest.approx(good_temp)


@pytest.mark.unit
@pytest.mark.parametrize("bad_tokens", [10, 63, 8193, 99999, -1, 1.5, "lots", None])
def test_resolve_max_tokens_out_of_bounds_falls_back(bad_tokens: Any) -> None:
    """Out-of-range or non-int max_tokens → settings default."""
    _, _, max_tokens = resolve_model_params(_model_params(max_tokens=bad_tokens))
    assert max_tokens == settings.generation_max_tokens


@pytest.mark.unit
@pytest.mark.parametrize("good_tokens", [64, 8192, 1024])
def test_resolve_max_tokens_inclusive_bounds_applied(good_tokens: int) -> None:
    """64 and 8192 are inclusive and pass through."""
    _, _, max_tokens = resolve_model_params(_model_params(max_tokens=good_tokens))
    assert max_tokens == good_tokens


@pytest.mark.unit
def test_resolve_model_choice_off_allowlist_falls_back() -> None:
    """A model outside the LiteLLM allowlist → settings.generation_model."""
    model, _, _ = resolve_model_params(_model_params(model_choice="evil-model"))
    assert model == settings.generation_model


@pytest.mark.unit
@pytest.mark.parametrize(
    "allowed",
    ["generation_model", "vision_model", "followup_model"],
)
def test_resolve_model_choice_allowlisted_applied(allowed: str) -> None:
    """Each allowlisted alias passes through unchanged."""
    choice = getattr(settings, allowed)
    model, _, _ = resolve_model_params(_model_params(model_choice=choice))
    assert model == choice


@pytest.mark.unit
def test_resolve_partial_override_only_temperature() -> None:
    """A lone valid temperature applies while the rest fall back."""
    model, temperature, max_tokens = resolve_model_params(
        _model_params(temperature=0.9)
    )
    assert temperature == pytest.approx(0.9)
    assert model == settings.generation_model
    assert max_tokens == settings.generation_max_tokens


@pytest.mark.unit
def test_resolve_empty_model_params_falls_back() -> None:
    """An ai_settings blob with no model_params key → settings triple."""
    assert resolve_model_params({"active_nodes": {}}) == _DEFAULT_TRIPLE


# ---------------------------------------------------------------------------
# merged_ai_settings round-trip (Phase 47/48 sub-blobs)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_merged_active_nodes_partial_preserves_defaults() -> None:
    """A single disabled toggle merges without dropping the others."""
    merged = merged_ai_settings({"active_nodes": {"build_carousel": False}})
    assert merged["active_nodes"]["build_carousel"] is False
    assert merged["active_nodes"]["sdr_persona"] is True
    assert merged["active_nodes"]["hitl_handover"] is True


@pytest.mark.unit
def test_merged_model_params_partial_preserves_defaults() -> None:
    """A partial model_params blob fills missing keys with None defaults."""
    merged = merged_ai_settings({"model_params": {"temperature": 0.7}})
    assert merged["model_params"]["temperature"] == pytest.approx(0.7)
    assert merged["model_params"]["max_tokens"] is None
    assert merged["model_params"]["model_choice"] is None
    # Resolver then honors the partial override end-to-end.
    _, temperature, max_tokens = resolve_model_params(merged)
    assert temperature == pytest.approx(0.7)
    assert max_tokens == settings.generation_max_tokens


@pytest.mark.unit
def test_default_blob_has_phase47_48_shape() -> None:
    """Regression guard on the canonical blob keys the wiring depends on."""
    assert set(DEFAULT_AI_SETTINGS["active_nodes"]) == {
        "sentiment_analysis",
        "research_mode",
        "inject_product_context",
        "build_carousel",
        "sdr_persona",
        "hitl_handover",
    }
    assert set(DEFAULT_AI_SETTINGS["model_params"]) == {
        "temperature",
        "max_tokens",
        "model_choice",
    }
