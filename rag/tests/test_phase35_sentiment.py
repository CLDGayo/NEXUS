"""Phase 35 — sentiment analysis node + generate_node overlay tests."""

from unittest.mock import AsyncMock, patch

import pytest

from rag.orchestrator.nodes import (
    _EXCITED_OVERLAY,
    _FRUSTRATED_OVERLAY,
    _URGENT_OVERLAY,
    _VALID_SENTIMENTS,
    _get_sentiment_overlay,
    sentiment_analysis_node,
)


@pytest.mark.asyncio
async def test_sentiment_returns_valid_category() -> None:
    """Node returns one of the four valid sentiments."""
    state = {"query": "I am so angry, nothing works!!!", "surface": "messenger"}
    with patch("rag.orchestrator.nodes.chat_complete", new_callable=AsyncMock) as mock:
        mock.return_value.content = "frustrated"
        result = await sentiment_analysis_node(state)
    assert result["sentiment"] in _VALID_SENTIMENTS


@pytest.mark.asyncio
async def test_sentiment_defaults_to_neutral_on_llm_error() -> None:
    """LLM failure must never crash — defaults to neutral."""
    from rag.orchestrator.llm import LLMError

    state = {"query": "hello", "surface": "messenger"}
    with patch("rag.orchestrator.nodes.chat_complete", new_callable=AsyncMock) as mock:
        mock.side_effect = LLMError("timeout")
        result = await sentiment_analysis_node(state)
    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_sentiment_defaults_to_neutral_on_garbage() -> None:
    """Unparseable LLM output falls back to neutral."""
    state = {"query": "test", "surface": "messenger"}
    with patch("rag.orchestrator.nodes.chat_complete", new_callable=AsyncMock) as mock:
        mock.return_value.content = "I think the user is somewhat upset"
        result = await sentiment_analysis_node(state)
    assert result["sentiment"] == "neutral"


@pytest.mark.asyncio
async def test_sentiment_empty_query() -> None:
    """Empty query skips LLM call and returns neutral."""
    state = {"query": "", "surface": "messenger"}
    result = await sentiment_analysis_node(state)
    assert result["sentiment"] == "neutral"


def test_get_sentiment_overlay() -> None:
    """Helper returns correct overlay or empty string."""
    assert _get_sentiment_overlay("frustrated") == _FRUSTRATED_OVERLAY
    assert _get_sentiment_overlay("urgent") == _URGENT_OVERLAY
    assert _get_sentiment_overlay("excited") == _EXCITED_OVERLAY
    assert _get_sentiment_overlay("neutral") == ""
    assert _get_sentiment_overlay(None) == ""
