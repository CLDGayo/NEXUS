"""Phase 25.1 — SSE consumer must yield a ``token`` event when the graph
swaps ``state["answer"]`` in a late node (``respond`` or ``abstain``).

Pre-fix, the streamer only emitted ``token`` from ``on_chain_end name="generate"``.
When generate produced an empty answer (e.g. Groq refused without the
abstention phrase), guardrails routed to ``abstain_node`` which rewrote
the answer to ``handover_fallback_text()`` — but the streamer silently
updated ``final_answer`` and never emitted a ``token`` event. The SPA
rendered the citations strip and zero message text. This was the "ghost
query" bug.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

from typing import Any, AsyncIterator

import pytest


class _FakeGraph:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def astream_events(
        self, state: dict, *, config: dict, version: str
    ) -> AsyncIterator[dict[str, Any]]:
        for ev in self._events:
            yield ev


def _install_fake_graph(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    fake = _FakeGraph(events)
    # The streamer does a deferred ``from rag.orchestrator.graph import get_graph``,
    # so monkeypatching the function on the module is enough.
    import rag.orchestrator.graph as graph_module

    monkeypatch.setattr(graph_module, "get_graph", lambda: fake)


async def _drain(stream) -> list[dict[str, Any]]:
    return [event async for event in stream]


@pytest.fixture
def silence_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the streamer from making a real Groq call for follow-ups."""

    async def _no_followups(_q: str, _a: str) -> list[str]:
        return []

    monkeypatch.setattr("routers.chat.generate_followups", _no_followups)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_abstain_text_streamed_when_generate_returned_empty(
    monkeypatch: pytest.MonkeyPatch, silence_followups: None
) -> None:
    abstain_text = (
        "I don't have confident information on that in our knowledge base. "
        "Reply with a few more details and I'll route you to a human agent on our team."
    )
    events = [
        {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {"output": {"reranked": []}},
        },
        {"event": "on_chain_start", "name": "generate", "data": {}},
        {
            "event": "on_chain_end",
            "name": "generate",
            "data": {"output": {"answer": ""}},
        },
        {
            "event": "on_chain_end",
            "name": "abstain",
            "data": {"output": {"answer": abstain_text}},
        },
    ]
    _install_fake_graph(monkeypatch, events)

    from routers.chat import _stream_graph_events

    yielded = await _drain(
        _stream_graph_events("conceptual question", "tk", None, None, None)
    )

    token_events = [e for e in yielded if e["type"] == "token"]
    assert len(token_events) == 1
    assert token_events[0]["content"] == abstain_text

    final = next(e for e in yielded if e["type"] == "__final__")
    assert final["answer"] == abstain_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_token_not_duplicated_when_abstain_silent(
    monkeypatch: pytest.MonkeyPatch, silence_followups: None
) -> None:
    """When generate produced a non-empty answer and abstain doesn't fire,
    only one ``token`` event must be yielded."""

    events = [
        {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {"output": {"reranked": []}},
        },
        {"event": "on_chain_start", "name": "generate", "data": {}},
        {
            "event": "on_chain_end",
            "name": "generate",
            "data": {"output": {"answer": "real answer [1]"}},
        },
    ]
    _install_fake_graph(monkeypatch, events)

    from routers.chat import _stream_graph_events

    yielded = await _drain(
        _stream_graph_events("real question", "tk", None, None, None)
    )

    token_events = [e for e in yielded if e["type"] == "token"]
    assert len(token_events) == 1
    assert token_events[0]["content"] == "real answer [1]"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_respond_branch_emits_token_when_no_generate_token(
    monkeypatch: pytest.MonkeyPatch, silence_followups: None
) -> None:
    """Same fix applies to the ``respond`` node path: if generate is silent
    and ``respond`` injects the final answer, that text must reach the SPA."""

    events = [
        {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {"output": {"reranked": []}},
        },
        {
            "event": "on_chain_end",
            "name": "respond",
            "data": {"output": {"answer": "respond-node text"}},
        },
    ]
    _install_fake_graph(monkeypatch, events)

    from routers.chat import _stream_graph_events

    yielded = await _drain(
        _stream_graph_events("q", "tk", None, None, None)
    )

    token_events = [e for e in yielded if e["type"] == "token"]
    assert len(token_events) == 1
    assert token_events[0]["content"] == "respond-node text"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_abstain_with_same_text_as_generate_does_not_double_emit(
    monkeypatch: pytest.MonkeyPatch, silence_followups: None
) -> None:
    """Defensive guard: if for some reason abstain produces the same text
    generate already emitted, the streamer must not double-emit."""

    answer = "same string"
    events = [
        {
            "event": "on_chain_end",
            "name": "rerank",
            "data": {"output": {"reranked": []}},
        },
        {
            "event": "on_chain_end",
            "name": "generate",
            "data": {"output": {"answer": answer}},
        },
        {
            "event": "on_chain_end",
            "name": "abstain",
            "data": {"output": {"answer": answer}},
        },
    ]
    _install_fake_graph(monkeypatch, events)

    from routers.chat import _stream_graph_events

    yielded = await _drain(
        _stream_graph_events("q", "tk", None, None, None)
    )

    token_events = [e for e in yielded if e["type"] == "token"]
    assert len(token_events) == 1
