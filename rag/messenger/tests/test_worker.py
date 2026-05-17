"""Phase 6 outbound worker drain-loop tests.

Mocks the queue + httpx client; verifies retry vs DLQ branching at the
attempt cap, plus stop-event termination.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from rag.config import settings
from rag.messenger import worker
from rag.messenger.queue import QueuedItem


def _item(**overrides) -> QueuedItem:
    base = dict(
        correlation_id="corr_w",
        target_url="https://hook.x",
        payload={"reply": {"text": "hi"}},
        attempts=0,
    )
    base.update(overrides)
    return QueuedItem(**base)


class _MockQueue:
    def __init__(self, items: list[QueuedItem] | None = None) -> None:
        self._items = items or []
        self.due_items = AsyncMock(return_value=self._items)
        self.requeue = AsyncMock()
        self.dead_letter = AsyncMock()


class _ResponseStub:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _ClientStub:
    def __init__(self, response: _ResponseStub | None = None, raise_exc: Exception | None = None) -> None:
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url: str, *, json: dict) -> _ResponseStub:
        if self._raise_exc:
            raise self._raise_exc
        assert self._response is not None
        return self._response


def _factory(client: _ClientStub):
    return lambda: client


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_successful_send_does_not_requeue_or_dlq() -> None:
    items = [_item(attempts=1)]
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(200))
    counters = await worker._process_batch(items, queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    assert counters == {"delivered": 1, "requeued": 0, "dead_lettered": 0}
    queue.requeue.assert_not_awaited()
    queue.dead_letter.assert_not_awaited()


@pytest.mark.unit
async def test_5xx_requeues_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "outbound_max_attempts", 3, raising=False)
    items = [_item(attempts=0)]
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(503, "service down"))
    counters = await worker._process_batch(items, queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    assert counters["requeued"] == 1
    queue.requeue.assert_awaited_once()
    requeued = queue.requeue.await_args.args[0]
    assert requeued.attempts == 1
    assert requeued.next_attempt_ts > 0


@pytest.mark.unit
async def test_4xx_dead_letters_immediately() -> None:
    items = [_item(attempts=0)]
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(400, "bad payload"))
    counters = await worker._process_batch(items, queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    assert counters["dead_lettered"] == 1
    queue.dead_letter.assert_awaited_once()
    queue.requeue.assert_not_awaited()


@pytest.mark.unit
async def test_attempt_cap_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "outbound_max_attempts", 3, raising=False)
    # Item already attempted 2 times; the next failure (→ attempts=3) hits the cap.
    items = [_item(attempts=2)]
    queue = _MockQueue()
    client = _ClientStub(_ResponseStub(502))
    counters = await worker._process_batch(items, queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    assert counters == {"delivered": 0, "requeued": 0, "dead_lettered": 1}


@pytest.mark.unit
async def test_transport_error_is_retryable() -> None:
    items = [_item(attempts=0)]
    queue = _MockQueue()
    client = _ClientStub(raise_exc=httpx.ConnectError("refused"))
    counters = await worker._process_batch(items, queue=queue, client_factory=_factory(client))  # type: ignore[arg-type]
    assert counters["requeued"] == 1


# ---------------------------------------------------------------------------
# run_forever loop
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_run_forever_terminates_via_stop_event() -> None:
    queue = _MockQueue(items=[])
    stop = asyncio.Event()
    stop.set()  # already stopped
    await worker.run_forever(
        stop_event=stop,
        queue=queue,  # type: ignore[arg-type]
        client_factory=lambda: _ClientStub(_ResponseStub(200)),
        poll_seconds=0.01,
    )


@pytest.mark.unit
async def test_run_forever_processes_then_exits_on_iteration_limit() -> None:
    queue = _MockQueue(items=[_item()])
    queue.due_items = AsyncMock(side_effect=[[_item()], []])
    await worker.run_forever(
        queue=queue,  # type: ignore[arg-type]
        client_factory=lambda: _ClientStub(_ResponseStub(200)),
        poll_seconds=0.01,
        iteration_limit=1,
    )
    # First iteration drained one due item.
    assert queue.due_items.await_count >= 1
