"""Phase 6 Redis outbound queue tests.

Mocks the async Redis client end to end; no live Redis touched.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from rag.messenger.queue import QueuedItem, RedisOutboundQueue


def _item(**overrides) -> QueuedItem:
    base = dict(
        correlation_id="corr_a",
        target_url="https://hooks.example.com/inbound",
        payload={"hello": "world"},
        attempts=0,
        next_attempt_ts=0,
    )
    base.update(overrides)
    return QueuedItem(**base)


class _PipelineStub:
    def __init__(self, results: list) -> None:
        self._results = results
        self.zrangebyscore = AsyncMock()
        self.zremrangebyscore = AsyncMock()

    async def execute(self):
        return self._results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None


class _ClientStub:
    def __init__(self, *, due_items: list[str] | None = None) -> None:
        self.zadd = AsyncMock(return_value=1)
        self.lpush = AsyncMock(return_value=1)
        self.zcard = AsyncMock(return_value=42)
        self.llen = AsyncMock(return_value=7)
        self._due_items = due_items or []

    def pipeline(self, transaction: bool = True) -> _PipelineStub:  # noqa: D401
        return _PipelineStub(results=[self._due_items, len(self._due_items)])


@pytest.mark.unit
class TestQueuedItem:
    def test_to_from_json_round_trip(self) -> None:
        item = _item(attempts=2, next_attempt_ts=99, last_error="boom")
        roundtrip = QueuedItem.from_json(item.to_json())
        assert roundtrip == item

    def test_with_attempt_increments_and_sets_next_ts(self) -> None:
        item = _item(attempts=1, first_failed_at=100)
        updated = item.with_attempt(error="x", now=500, backoff_seconds=30)
        assert updated.attempts == 2
        assert updated.next_attempt_ts == 530
        assert updated.first_failed_at == 100
        assert updated.last_error == "x"

    def test_with_attempt_records_first_failure_when_none(self) -> None:
        item = _item(first_failed_at=None)
        updated = item.with_attempt(error="x", now=500, backoff_seconds=10)
        assert updated.first_failed_at == 500


@pytest.mark.unit
class TestRedisOutboundQueue:
    async def test_enqueue_zadds_with_explicit_ts(self) -> None:
        client = _ClientStub()
        q = RedisOutboundQueue(client=client)  # type: ignore[arg-type]
        item = _item(next_attempt_ts=12345)
        await q.enqueue(item)
        client.zadd.assert_awaited_once()
        call = client.zadd.await_args
        args, kwargs = call.args, call.kwargs
        # zadd(key, mapping) — second arg is the dict
        mapping = args[1]
        assert list(mapping.values())[0] == 12345
        assert "corr_a" in list(mapping.keys())[0]

    async def test_enqueue_uses_now_when_ts_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import rag.messenger.queue as queue_module
        monkeypatch.setattr(queue_module, "_now_epoch", lambda: 999)
        client = _ClientStub()
        q = RedisOutboundQueue(client=client)  # type: ignore[arg-type]
        await q.enqueue(_item(next_attempt_ts=0))
        mapping = client.zadd.await_args.args[1]
        assert list(mapping.values())[0] == 999

    async def test_due_items_decodes_and_drops_malformed(self) -> None:
        good = _item(correlation_id="ok").to_json()
        bad = "{not valid json}"
        client = _ClientStub(due_items=[good, bad])
        q = RedisOutboundQueue(client=client)  # type: ignore[arg-type]
        items = await q.due_items(now=500)
        assert len(items) == 1
        assert items[0].correlation_id == "ok"

    async def test_dead_letter_lpushes(self) -> None:
        client = _ClientStub()
        q = RedisOutboundQueue(client=client)  # type: ignore[arg-type]
        await q.dead_letter(_item(attempts=4, last_error="gave up"))
        client.lpush.assert_awaited_once()

    async def test_depth_and_dlq_depth(self) -> None:
        client = _ClientStub()
        q = RedisOutboundQueue(client=client)  # type: ignore[arg-type]
        assert await q.depth() == 42
        assert await q.dlq_depth() == 7
