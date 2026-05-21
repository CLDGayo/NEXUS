"""Phase 21 — ``append_history`` reducer discipline.

The reducer must:
  * keep ``{"role": str, "content": str}`` entries,
  * drop anything else (multimodal content blocks, non-dicts) with a
    structured log line,
  * cap total entries and total characters so a long-running thread
    doesn't bloat its checkpoint row past JSONB's practical ceiling.
"""

from __future__ import annotations

import logging

import pytest

from rag.orchestrator.state import (
    HISTORY_MAX_CHARS,
    HISTORY_MAX_ENTRIES,
    append_history,
)


@pytest.mark.unit
class TestShape:
    def test_appends_valid_text_entries(self) -> None:
        out = append_history(
            [{"role": "user", "content": "hi"}],
            [{"role": "assistant", "content": "hello"}],
        )
        assert out == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_drops_multimodal_content_block(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bad = {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
            ],
        }
        with caplog.at_level(logging.WARNING, logger="rag.orchestrator.state"):
            out = append_history([], [bad])
        assert out == []
        assert any(
            "state.history.dropped_nontext" in r.getMessage() for r in caplog.records
        )

    def test_drops_non_dict_entries(self) -> None:
        out = append_history([], ["not a dict", 42, None])  # type: ignore[list-item]
        assert out == []

    def test_drops_entries_missing_role_or_content(self) -> None:
        out = append_history(
            [],
            [
                {"content": "no role"},  # type: ignore[list-item]
                {"role": "user"},  # type: ignore[list-item]
                {"role": "user", "content": 12345},  # type: ignore[list-item]
            ],
        )
        assert out == []

    def test_none_inputs_treated_as_empty(self) -> None:
        assert append_history(None, None) == []
        assert append_history(None, [{"role": "user", "content": "x"}]) == [
            {"role": "user", "content": "x"}
        ]


@pytest.mark.unit
class TestCaps:
    def test_caps_at_max_entries(self) -> None:
        many = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(HISTORY_MAX_ENTRIES + 10)
        ]
        out = append_history([], many)
        assert len(out) == HISTORY_MAX_ENTRIES
        # Oldest trimmed — newest preserved.
        assert out[-1] == {
            "role": "user",
            "content": f"msg {HISTORY_MAX_ENTRIES + 9}",
        }

    def test_caps_total_chars(self) -> None:
        big = {"role": "user", "content": "x" * (HISTORY_MAX_CHARS // 2)}
        out = append_history([big, big, big], [big])
        total = sum(len(e["content"]) for e in out)
        assert total <= HISTORY_MAX_CHARS

    def test_appending_to_full_history_trims_oldest(self) -> None:
        prior = [
            {"role": "user", "content": f"old {i}"}
            for i in range(HISTORY_MAX_ENTRIES)
        ]
        out = append_history(prior, [{"role": "user", "content": "new"}])
        assert len(out) == HISTORY_MAX_ENTRIES
        assert out[-1] == {"role": "user", "content": "new"}
        assert out[0] == {"role": "user", "content": "old 1"}
