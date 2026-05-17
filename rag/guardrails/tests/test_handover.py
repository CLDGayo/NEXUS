"""Phase 5 handover signal tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from rag.guardrails import handover
from rag.guardrails.handover import (
    HandoverSignal,
    emit_handover_signal,
    handover_fallback_text,
)


def _signal(**overrides) -> HandoverSignal:
    defaults = dict(
        correlation_id="corr_abc",
        thread_key="psid_123",
        surface="messenger",
        reason="exact_match failed",
        validators_failed=("exact_match",),
        uncertainty_score=0.55,
        retrieved_count=4,
        answer_blocked=True,
    )
    defaults.update(overrides)
    return HandoverSignal(**defaults)


@pytest.mark.unit
class TestSignal:
    def test_as_dict_round_trip(self) -> None:
        signal = _signal()
        payload = signal.as_dict()
        assert payload["correlation_id"] == "corr_abc"
        assert payload["validators_failed"] == ["exact_match"]
        assert payload["answer_blocked"] is True
        assert payload["timestamp"]

    def test_timestamp_generated_when_not_supplied(self) -> None:
        signal = _signal()
        # ISO 8601 UTC includes 'T' and timezone marker
        assert "T" in signal.timestamp


@pytest.mark.unit
class TestEmit:
    def test_logs_warning_with_payload(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handover, "get_langfuse", lambda: None)
        caplog.set_level(logging.WARNING, logger="rag.guardrails.handover")
        emit_handover_signal(_signal())
        assert any(
            "handover_required" in record.message for record in caplog.records
        )

    def test_calls_langfuse_event_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_lf = MagicMock()
        monkeypatch.setattr(handover, "get_langfuse", lambda: fake_lf)
        emit_handover_signal(_signal())
        fake_lf.event.assert_called_once()
        call_kwargs = fake_lf.event.call_args.kwargs
        assert call_kwargs["name"] == "chat.handover_required"
        assert call_kwargs["level"] == "WARNING"

    def test_langfuse_failure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_lf = MagicMock()
        fake_lf.event.side_effect = RuntimeError("network down")
        monkeypatch.setattr(handover, "get_langfuse", lambda: fake_lf)
        # Must not raise
        emit_handover_signal(_signal())


@pytest.mark.unit
def test_fallback_text_constant() -> None:
    assert handover_fallback_text() == handover_fallback_text()
    assert handover_fallback_text()
