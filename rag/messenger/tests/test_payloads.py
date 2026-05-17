"""Phase 6 outbound payload schema + builder tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.messenger.payloads import (
    OutboundMetadata,
    OutboundPayload,
    ReplyBlock,
    TokenUsage,
    build_outbound_payload,
)
from rag.messenger.schemas import InboundMessage


def _inbound(**overrides) -> InboundMessage:
    base = dict(
        user_id="psid_12345",
        message_text="hello",
        timestamp=1731742800,
        channel="messenger",
        page_id="page_1",
    )
    base.update(overrides)
    return InboundMessage(**base)


@pytest.mark.unit
class TestSchemas:
    def test_token_usage_defaults(self) -> None:
        usage = TokenUsage()
        assert usage.prompt == 0
        assert usage.completion == 0
        assert usage.total == 0

    def test_token_usage_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            TokenUsage(prompt=-1)

    def test_reply_block_min_text_length(self) -> None:
        with pytest.raises(ValidationError):
            ReplyBlock(text="")

    def test_reply_block_uncertainty_bounded(self) -> None:
        with pytest.raises(ValidationError):
            ReplyBlock(text="x", uncertainty_score=1.5)

    def test_outbound_payload_strict(self) -> None:
        # extra="forbid" should reject unknown keys
        with pytest.raises(ValidationError):
            OutboundPayload(
                correlation_id="c",
                user_id="u",
                channel="messenger",
                reply=ReplyBlock(text="ok"),
                metadata=OutboundMetadata(),
                unexpected="x",
            )


@pytest.mark.unit
class TestBuilder:
    def test_builds_from_minimal_graph_result(self) -> None:
        inbound = _inbound()
        out = build_outbound_payload(
            inbound=inbound,
            correlation_id="corr_abc",
            reply_text="Plan [1] works. Reply YES to book.",
            graph_result={},
        )
        assert out.correlation_id == "corr_abc"
        assert out.user_id == "psid_12345"
        assert out.channel == "messenger"
        assert out.page_id == "page_1"
        assert out.reply.text == "Plan [1] works. Reply YES to book."
        assert out.reply.citations == []
        assert out.reply.requires_human_handover is False
        assert out.reply.uncertainty_score == 0.0
        assert out.metadata.tokens.total == 0
        assert out.metadata.surface == "messenger"
        assert out.metadata.abstained is False

    def test_carries_through_token_usage(self) -> None:
        inbound = _inbound()
        out = build_outbound_payload(
            inbound=inbound,
            correlation_id="corr_x",
            reply_text="text",
            graph_result={
                "llm_prompt_tokens": 120,
                "llm_completion_tokens": 24,
                "llm_total_tokens": 144,
                "llm_latency_ms": 850,
                "llm_model": "groq-llama-3.3-70b",
            },
        )
        assert out.metadata.tokens.prompt == 120
        assert out.metadata.tokens.completion == 24
        assert out.metadata.tokens.total == 144
        assert out.metadata.latency_ms == 850
        assert out.metadata.model == "groq-llama-3.3-70b"

    def test_handover_signal_propagates(self) -> None:
        inbound = _inbound()
        out = build_outbound_payload(
            inbound=inbound,
            correlation_id="corr_y",
            reply_text="abstention text",
            graph_result={
                "requires_human_handover": True,
                "handover_reason": "exact_match: $147.99",
                "validator_failures": ("exact_match",),
                "uncertainty_score": 0.85,
                "abstained": True,
            },
        )
        assert out.reply.requires_human_handover is True
        assert out.reply.handover_reason == "exact_match: $147.99"
        assert out.reply.validator_failures == ["exact_match"]
        assert out.reply.uncertainty_score == pytest.approx(0.85)
        assert out.metadata.abstained is True
