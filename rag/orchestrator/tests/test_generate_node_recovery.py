"""Phase 40 — generate_node outbound_recovery surface branch tests.

Verifies:
  1. system_recovery.md content appears in messages[0]["content"]
  2. SDR tools are NOT bound (extra kwarg is None / absent)
  3. Cart directive is NOT leaked into history reducer output
  4. Guardrail pipeline bypasses citation + exact_match for outbound_recovery
  5. checkout_url from cart_context appears in the rendered system message
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from rag.orchestrator import nodes as nodes_module
from rag.orchestrator.llm import LLMResult
from rag.retrieval.types import ScoredChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECOVERY_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_recovery.md"


def _llm_text(content: str = "Hey! You left something in your cart.") -> LLMResult:
    return LLMResult(
        content=content,
        model="m",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=50,
    )


def _chunk(idx: int = 1) -> ScoredChunk:
    return ScoredChunk(
        id=f"c-{idx}",
        text="product context",
        score=1.0,
        metadata={"title": f"Note {idx}"},
    )


def _recovery_state(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "query": "[outbound_recovery]",
        "thread_key": "psid_123",
        "correlation_id": "cart_cart-001",
        "surface": "outbound_recovery",
        "tenant_id": "hunter",
        "sender_id": "psid_123",
        "reranked": [_chunk(1)],
        "cart_context": {
            "cart_items": ["1x Brix Signature Tee"],
            "checkout_url": "https://example.com/checkout/abc",
        },
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Test: recovery prompt is loaded and injected into messages[0]
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGenerateNodeLoadsRecoveryPrompt:
    async def test_generate_node_loads_recovery_prompt(self) -> None:
        """system_recovery.md content must appear in the system message sent to LLM."""
        state = _recovery_state()
        captured_messages: list[Any] = []

        async def _capture_chat_complete(messages, **kwargs):
            captured_messages.extend(messages)
            return _llm_text()

        with patch.object(nodes_module, "chat_complete", _capture_chat_complete):
            await nodes_module.generate_node(state)

        assert captured_messages, "chat_complete was never called"
        system_msg = captured_messages[0]
        assert system_msg["role"] == "system"

        # The recovery prompt file must exist and its content must be present
        assert _RECOVERY_PROMPT_PATH.exists(), (
            f"system_recovery.md not found at {_RECOVERY_PROMPT_PATH}"
        )
        # At minimum, the checkout_url slot value must have been injected
        assert "https://example.com/checkout/abc" in system_msg["content"], (
            "checkout_url not found in system message"
        )
        # Cart item must appear in the rendered prompt
        assert "Brix Signature Tee" in system_msg["content"]


# ---------------------------------------------------------------------------
# Test: SDR tools NOT bound for outbound_recovery
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGenerateNodeNoSdrTools:
    async def test_generate_node_no_sdr_tools_for_recovery(self) -> None:
        """extra kwarg passed to chat_complete must be None for outbound_recovery."""
        state = _recovery_state()
        captured_extras: list[Any] = []

        async def _capture_chat_complete(messages, *, extra=None, **kwargs):
            captured_extras.append(extra)
            return _llm_text()

        with patch.object(nodes_module, "chat_complete", _capture_chat_complete):
            await nodes_module.generate_node(state)

        assert len(captured_extras) >= 1, "chat_complete was never called"
        # All calls (should be just one for recovery) must have extra=None
        for extra in captured_extras:
            assert extra is None, (
                f"SDR tools must not be bound for outbound_recovery surface; got extra={extra}"
            )


# ---------------------------------------------------------------------------
# Test: history non-pollution — cart directive NOT in returned history
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestPromptOverlayNotInHistory:
    async def test_prompt_overlay_not_in_history(self) -> None:
        """generate_node must NOT return a history key with user-role cart content."""
        state = _recovery_state()

        async def _stub_chat_complete(messages, **kwargs):
            return _llm_text("Here's your cart — come back!")

        with patch.object(nodes_module, "chat_complete", _stub_chat_complete):
            result = await nodes_module.generate_node(state)

        # The returned dict must not contain a 'history' key
        assert "history" not in result, (
            "generate_node must not return a history key for outbound_recovery"
        )
        # And the answer must not contain the sentinel query
        answer = result.get("answer", "")
        assert "[outbound_recovery]" not in answer


# ---------------------------------------------------------------------------
# Test: guardrail bypass for outbound_recovery surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGuardrailBypassForRecoverySurface:
    def test_guardrail_bypass_for_recovery_surface(self) -> None:
        """citation + exact_match must be bypassed; entropy validator still runs.

        The answer is kept long enough (>40 words) to avoid the pre-existing
        short-turn bypass, which fires before the outbound_recovery bypass in
        the pipeline loop. This ensures the outbound_recovery branch is the
        one that produces the bypass reason, not the short-turn guard.
        """
        from rag.guardrails.pipeline import default_pipeline

        pipeline = default_pipeline()
        # Answer > 40 words + query > 8 words so short-turn bypass does NOT fire.
        answer = (
            "Hey there! You left a Brix Signature Tee in your cart and we wanted "
            "to make sure you don't miss out on this one — it's been really popular "
            "lately. Tap the link below to complete your order whenever you're ready, "
            "and reach out if you have any questions at all about sizing or shipping. "
            "We'd love to help you lock it in today."
        )
        query = "[outbound_recovery] cart_id=cart-001 psid=psid_123 tenant=hunter"
        # Use empty retrieved list — citation validator would block without bypass
        out = pipeline.validate(
            answer,
            retrieved=[],
            query=query,
            surface="outbound_recovery",
        )

        citation_result = next(r for r in out.results if r.name == "citation")
        exact_match_result = next(r for r in out.results if r.name == "exact_match")

        assert citation_result.passed, "citation must be bypassed for outbound_recovery"
        assert citation_result.reason == "outbound_recovery_bypass", (
            f"expected 'outbound_recovery_bypass' but got '{citation_result.reason}'"
        )
        assert exact_match_result.passed, (
            "exact_match must be bypassed for outbound_recovery"
        )
        assert exact_match_result.reason == "outbound_recovery_bypass", (
            f"expected 'outbound_recovery_bypass' but got '{exact_match_result.reason}'"
        )

        # entropy validator must still have run (not bypassed)
        entropy_result = next(r for r in out.results if r.name == "entropy")
        assert entropy_result.metadata.get("bypassed") is not True, (
            "entropy validator must NOT be bypassed for outbound_recovery"
        )


# ---------------------------------------------------------------------------
# Test: checkout_url injected into rendered prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCheckoutUrlInRenderedPrompt:
    async def test_checkout_url_in_rendered_prompt(self) -> None:
        """The checkout_url from cart_context must appear in messages[0]['content']."""
        checkout_url = "https://store.example.com/checkout/xyz-789"
        state = _recovery_state(
            cart_context={
                "cart_items": ["2x Limited Edition Print"],
                "checkout_url": checkout_url,
            }
        )
        captured_system_content: list[str] = []

        async def _capture(messages, **kwargs):
            if messages and messages[0]["role"] == "system":
                captured_system_content.append(str(messages[0]["content"]))
            return _llm_text()

        with patch.object(nodes_module, "chat_complete", _capture):
            await nodes_module.generate_node(state)

        assert captured_system_content, "chat_complete was never called"
        assert checkout_url in captured_system_content[0], (
            f"checkout_url '{checkout_url}' not found in system message: "
            f"{captured_system_content[0][:300]}"
        )
