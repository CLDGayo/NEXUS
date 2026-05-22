"""``append_history`` reducer discipline.

Phase 21 — text-only shape, entry/char caps, drop log lines.
Phase 22 — rolling 7-day TTL, timestamp preservation, legacy-entry grace
period.

The reducer must:
  * keep ``{"role": str, "content": str}`` entries (timestamp optional),
  * drop anything else (multimodal content blocks, non-dicts) with a
    structured log line,
  * cap total entries and total characters so a long-running thread
    doesn't bloat its checkpoint row past JSONB's practical ceiling,
  * stamp incoming entries with the current epoch when no timestamp is
    supplied, and drop merged entries older than ``HISTORY_TTL_SECONDS``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from rag.orchestrator.state import (
    HISTORY_MAX_CHARS,
    HISTORY_MAX_ENTRIES,
    HISTORY_TTL_SECONDS,
    append_history,
)


def _strip_ts(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return entries with only ``role`` and ``content`` keys for equality
    assertions that don't care about timestamps."""

    return [
        {"role": str(e["role"]), "content": str(e["content"])} for e in entries
    ]


@pytest.mark.unit
class TestShape:
    def test_appends_valid_text_entries(self) -> None:
        out = append_history(
            [{"role": "user", "content": "hi"}],
            [{"role": "assistant", "content": "hello"}],
        )
        assert _strip_ts(out) == [
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
        out = append_history(None, [{"role": "user", "content": "x"}])
        assert _strip_ts(out) == [{"role": "user", "content": "x"}]


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
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == f"msg {HISTORY_MAX_ENTRIES + 9}"

    def test_caps_total_chars(self) -> None:
        big = {"role": "user", "content": "x" * (HISTORY_MAX_CHARS // 2)}
        out = append_history([big, big, big], [big])
        total = sum(len(str(e["content"])) for e in out)
        assert total <= HISTORY_MAX_CHARS

    def test_appending_to_full_history_trims_oldest(self) -> None:
        prior = [
            {"role": "user", "content": f"old {i}"}
            for i in range(HISTORY_MAX_ENTRIES)
        ]
        out = append_history(prior, [{"role": "user", "content": "new"}])
        assert len(out) == HISTORY_MAX_ENTRIES
        assert out[-1]["content"] == "new"
        # "old 0" got evicted; "old 1" is now the oldest.
        assert out[0]["content"] == "old 1"


@pytest.mark.unit
class TestTTL:
    def test_appended_entry_without_timestamp_is_stamped_with_now(self) -> None:
        before = time.time()
        out = append_history([], [{"role": "user", "content": "hi"}])
        after = time.time()
        assert len(out) == 1
        ts = out[0]["timestamp"]
        assert isinstance(ts, float)
        assert before <= ts <= after

    def test_appended_entry_preserves_explicit_timestamp(self) -> None:
        explicit_ts = time.time() - 60  # one minute ago, still inside TTL
        out = append_history(
            [],
            [
                {
                    "role": "user",
                    "content": "hello",
                    "timestamp": explicit_ts,
                }
            ],
        )
        assert out[0]["timestamp"] == pytest.approx(explicit_ts)

    def test_evicts_entry_older_than_ttl(self) -> None:
        ancient_ts = time.time() - HISTORY_TTL_SECONDS - 3600  # 1h past TTL
        out = append_history(
            [
                {
                    "role": "user",
                    "content": "ancient",
                    "timestamp": ancient_ts,
                }
            ],
            [{"role": "user", "content": "fresh"}],
        )
        contents = [e["content"] for e in out]
        assert "ancient" not in contents
        assert "fresh" in contents

    def test_legacy_entry_without_timestamp_gets_grace_period(self) -> None:
        # Pre-Phase-22 state: history dicts have no timestamp key. On the
        # next reduction they should be stamped with `now` and kept (one
        # full TTL window of grace).
        legacy = {"role": "user", "content": "from before phase 22"}
        before = time.time()
        out = append_history([legacy], [{"role": "user", "content": "new"}])
        after = time.time()
        assert len(out) == 2
        legacy_out = next(e for e in out if e["content"] == "from before phase 22")
        ts = legacy_out["timestamp"]
        assert isinstance(ts, float)
        assert before <= ts <= after

    def test_rejects_entry_with_non_numeric_timestamp(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="rag.orchestrator.state"):
            out = append_history(
                [],
                [
                    {
                        "role": "user",
                        "content": "weird",
                        "timestamp": "yesterday",  # type: ignore[list-item]
                    }
                ],
            )
        assert out == []
        assert any(
            "state.history.dropped_nontext" in r.getMessage() for r in caplog.records
        )

    def test_mixed_fresh_and_expired_entries(self) -> None:
        now = time.time()
        out = append_history(
            [
                {
                    "role": "user",
                    "content": "expired",
                    "timestamp": now - HISTORY_TTL_SECONDS - 1,
                },
                {
                    "role": "user",
                    "content": "borderline_fresh",
                    "timestamp": now - HISTORY_TTL_SECONDS + 60,
                },
            ],
            [],
        )
        contents = [e["content"] for e in out]
        assert contents == ["borderline_fresh"]
