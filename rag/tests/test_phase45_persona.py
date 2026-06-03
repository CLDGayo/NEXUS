"""Phase 45 — Lifecycle Persona Engine: hermetic unit tests.

All tests are @pytest.mark.unit — no network, no database, no filesystem
access beyond the module under test.

Coverage
--------
* merged_ai_settings  — partial blob upcast, None, extra keys preserved.
* assemble_system_prompt — each situational branch, priority order, empty-
  skip, core_behavior always-on.
* _is_first_turn / _is_buy_intent — predicate correctness.
* test_ai_settings_defaults_noop — DEFAULT_AI_SETTINGS tenant produces an
  EMPTY suffix (byte-identical behavior regression guard).
"""

from __future__ import annotations

import pytest

from rag.orchestrator.ai_settings import (
    DEFAULT_AI_SETTINGS,
    _is_buy_intent,
    _is_first_turn,
    assemble_system_prompt,
    merged_ai_settings,
)


# ---------------------------------------------------------------------------
# merged_ai_settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_merged_ai_settings_none_returns_full_default() -> None:
    """None raw → full copy of DEFAULT_AI_SETTINGS."""
    result = merged_ai_settings(None)
    assert result == DEFAULT_AI_SETTINGS
    # Must be a copy, not the same object.
    assert result is not DEFAULT_AI_SETTINGS


@pytest.mark.unit
def test_merged_ai_settings_empty_dict_returns_full_default() -> None:
    result = merged_ai_settings({})
    assert result == DEFAULT_AI_SETTINGS


@pytest.mark.unit
def test_merged_ai_settings_partial_blob_fills_missing_keys() -> None:
    """Partial scenario_prompts sub-dict is merged with defaults."""
    raw = {
        "scenario_prompts": {"core_behavior": "Be polite."},
    }
    result = merged_ai_settings(raw)
    assert result["scenario_prompts"]["core_behavior"] == "Be polite."
    # Keys absent from raw are filled from the default.
    assert result["scenario_prompts"]["introduction"] == ""
    assert result["scenario_prompts"]["checkout_transition"] == ""
    assert result["scenario_prompts"]["human_handoff"] == ""
    # Unrelated top-level keys come from default.
    assert result["active_nodes"] == DEFAULT_AI_SETTINGS["active_nodes"]
    assert result["model_params"] == DEFAULT_AI_SETTINGS["model_params"]


@pytest.mark.unit
def test_merged_ai_settings_active_nodes_partial() -> None:
    raw = {"active_nodes": {"sentiment_analysis": False}}
    result = merged_ai_settings(raw)
    assert result["active_nodes"]["sentiment_analysis"] is False
    # All other nodes still default to True.
    assert result["active_nodes"]["research_mode"] is True
    assert result["active_nodes"]["sdr_persona"] is True


@pytest.mark.unit
def test_merged_ai_settings_unknown_sub_keys_preserved() -> None:
    """Forward-compatible: unknown sub-keys survive round-trip."""
    raw = {"scenario_prompts": {"future_key": "value"}}
    result = merged_ai_settings(raw)
    assert result["scenario_prompts"]["future_key"] == "value"


@pytest.mark.unit
def test_merged_ai_settings_does_not_mutate_default() -> None:
    """Merging with non-empty raw must never mutate DEFAULT_AI_SETTINGS."""
    original_core = DEFAULT_AI_SETTINGS["scenario_prompts"]["core_behavior"]
    merged_ai_settings({"scenario_prompts": {"core_behavior": "mutate me"}})
    assert DEFAULT_AI_SETTINGS["scenario_prompts"]["core_behavior"] == original_core


# ---------------------------------------------------------------------------
# _is_first_turn / _is_buy_intent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_first_turn_empty_history() -> None:
    assert _is_first_turn({}) is True  # type: ignore[arg-type]
    assert _is_first_turn({"history": []}) is True  # type: ignore[arg-type]


@pytest.mark.unit
def test_is_first_turn_with_history() -> None:
    state = {"history": [{"role": "user", "content": "hi"}]}
    assert _is_first_turn(state) is False  # type: ignore[arg-type]


@pytest.mark.unit
def test_is_buy_intent_no_products() -> None:
    assert _is_buy_intent({}) is False  # type: ignore[arg-type]
    assert _is_buy_intent({"_enriched_products": []}) is False  # type: ignore[arg-type]
    assert _is_buy_intent({"_enriched_products": None}) is False  # type: ignore[arg-type]


@pytest.mark.unit
def test_is_buy_intent_with_products() -> None:
    state = {"_enriched_products": [{"id": "1", "name": "Widget"}]}
    assert _is_buy_intent(state) is True  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assemble_system_prompt
# ---------------------------------------------------------------------------


def _make_ai_settings(
    core_behavior: str = "",
    introduction: str = "",
    checkout_transition: str = "",
    human_handoff: str = "",
) -> dict:
    """Build a minimal ai_settings dict with the given scenario_prompts."""
    return {
        "scenario_prompts": {
            "core_behavior": core_behavior,
            "introduction": introduction,
            "checkout_transition": checkout_transition,
            "human_handoff": human_handoff,
        }
    }


@pytest.mark.unit
def test_assemble_returns_empty_for_all_empty_prompts() -> None:
    """All-empty scenario_prompts → empty suffix."""
    ai = _make_ai_settings()
    suffix = assemble_system_prompt("BASE", ai, {})  # type: ignore[arg-type]
    assert suffix == ""


@pytest.mark.unit
def test_assemble_core_behavior_always_appended() -> None:
    """core_behavior alone → appears in suffix regardless of state."""
    ai = _make_ai_settings(core_behavior="Always be kind.")
    # No history, no products, no handover.
    suffix = assemble_system_prompt("BASE", ai, {})  # type: ignore[arg-type]
    assert "Always be kind." in suffix


@pytest.mark.unit
def test_assemble_introduction_on_first_turn() -> None:
    ai = _make_ai_settings(introduction="Hello! I'm Seina.")
    state: dict = {}  # no history → first turn
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "Hello! I'm Seina." in suffix


@pytest.mark.unit
def test_assemble_introduction_not_on_second_turn() -> None:
    ai = _make_ai_settings(introduction="Hello! I'm Seina.")
    state = {"history": [{"role": "user", "content": "hi"}]}
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "Hello! I'm Seina." not in suffix


@pytest.mark.unit
def test_assemble_checkout_transition_on_buy_intent() -> None:
    ai = _make_ai_settings(checkout_transition="You can checkout now.")
    state = {"_enriched_products": [{"id": "1"}]}
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "You can checkout now." in suffix


@pytest.mark.unit
def test_assemble_human_handoff_fires_first() -> None:
    """human_handoff has highest priority — beats checkout_transition."""
    ai = _make_ai_settings(
        human_handoff="Transferring you now.",
        checkout_transition="Buy this!",
        introduction="Hi!",
    )
    state = {
        "requires_human_handover": True,
        "_enriched_products": [{"id": "1"}],
        "history": [],  # first turn too
    }
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "Transferring you now." in suffix
    # Must NOT include checkout or intro when handoff takes priority.
    assert "Buy this!" not in suffix
    assert "Hi!" not in suffix


@pytest.mark.unit
def test_assemble_checkout_beats_introduction() -> None:
    """checkout_transition priority > introduction."""
    ai = _make_ai_settings(
        checkout_transition="Buy this!",
        introduction="Hi!",
    )
    state = {
        "_enriched_products": [{"id": "1"}],
        "history": [],  # also first turn
    }
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "Buy this!" in suffix
    assert "Hi!" not in suffix


@pytest.mark.unit
def test_assemble_exactly_one_situational() -> None:
    """Only one situational block fires even when multiple signals are true."""
    ai = _make_ai_settings(
        human_handoff="Handoff text.",
        checkout_transition="Checkout text.",
        introduction="Intro text.",
    )
    state = {
        "requires_human_handover": True,
        "_enriched_products": [{"id": "1"}],
        "history": [],
    }
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    # Count occurrences — each phrase appears at most once.
    assert suffix.count("Handoff text.") == 1
    assert "Checkout text." not in suffix
    assert "Intro text." not in suffix


@pytest.mark.unit
def test_assemble_empty_situational_skipped() -> None:
    """Empty situational string is not appended even when state matches."""
    # requires_human_handover set but human_handoff prompt is empty.
    ai = _make_ai_settings(human_handoff="")
    state = {"requires_human_handover": True}
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert suffix == ""


@pytest.mark.unit
def test_assemble_core_plus_situational_both_present() -> None:
    """core_behavior AND a situational both appear when non-empty."""
    ai = _make_ai_settings(
        core_behavior="Be professional.",
        introduction="Welcome!",
    )
    state: dict = {}  # first turn
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert "Be professional." in suffix
    assert "Welcome!" in suffix


@pytest.mark.unit
def test_assemble_whitespace_only_strings_skipped() -> None:
    """Whitespace-only scenario prompts are treated as empty."""
    ai = _make_ai_settings(core_behavior="   ", introduction="  ")
    state: dict = {}
    suffix = assemble_system_prompt("BASE", ai, state)  # type: ignore[arg-type]
    assert suffix == ""


# ---------------------------------------------------------------------------
# Regression guard: DEFAULT_AI_SETTINGS tenant produces empty suffix
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ai_settings_defaults_noop() -> None:
    """A tenant with DEFAULT_AI_SETTINGS produces an EMPTY persona suffix.

    This is the critical regression guard: default tenants must receive
    byte-identical system prompts to pre-Phase-45. Any non-empty suffix
    from the default blob would change live behavior for every tenant
    on deploy.
    """
    merged = merged_ai_settings(None)  # full default blob

    # Try all state combinations that could trigger a situational branch.
    states: list[dict] = [
        {},  # first turn, no products, no handover
        {"history": [{"role": "user", "content": "hi"}]},  # second turn
        {"_enriched_products": [{"id": "p1"}]},  # buy intent
        {"requires_human_handover": True},  # handover
        {  # all three signals simultaneously
            "requires_human_handover": True,
            "_enriched_products": [{"id": "p1"}],
            "history": [],
        },
    ]

    for state in states:
        suffix = assemble_system_prompt("BASE_PROMPT", merged, state)  # type: ignore[arg-type]
        assert suffix == "", (
            f"DEFAULT_AI_SETTINGS produced a non-empty suffix for state={state!r}: "
            f"{suffix!r}"
        )
