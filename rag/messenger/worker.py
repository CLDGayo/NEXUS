"""Outbound retry worker — drains the Redis queue and retries deliveries.

Run as a long-lived process alongside the API container::

    python -m rag.messenger.worker

The drain loop:
    1. Pop items due now via the queue's atomic ZRANGE+ZREM.
    2. For each item, send to its target_url with the same timeout the
       optimistic path uses.
    3. On success: nothing — the queue already removed the item.
    4. On retryable failure: requeue with the next backoff interval, or
       dead-letter if attempts exceed ``OUTBOUND_MAX_ATTEMPTS``.
    5. On non-retryable failure (4xx): dead-letter immediately.

A small ``asyncio.Event`` stop signal makes the worker testable + lets a
SIGTERM handler shut it down cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Any

import httpx

from rag.config import settings
from rag.messenger.queue import (
    QueuedItem,
    RedisOutboundQueue,
    get_queue,
)
from rag.messenger_overlay import current_page_access_token

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0/me/messages"
_FB_AUTH_ERROR_CODES: frozenset[int] = frozenset({190, 100, 200, 10})
_FB_RATE_LIMIT_CODES: frozenset[int] = frozenset({4, 17, 613})

_log = logging.getLogger(__name__)


def _now_epoch() -> int:
    return int(time.time())


def _classify_graph_error(status_code: int, body: Any) -> tuple[bool, str]:
    err = (body or {}).get("error") if isinstance(body, dict) else None
    code = int((err or {}).get("code", 0) or 0)
    subcode = int((err or {}).get("error_subcode", 0) or 0)
    msg = str((err or {}).get("message") or "")[:200]
    summary = f"http {status_code} code={code} subcode={subcode}: {msg}".strip()

    if code in _FB_RATE_LIMIT_CODES or subcode in _FB_RATE_LIMIT_CODES:
        return True, summary
    if code in _FB_AUTH_ERROR_CODES or subcode in _FB_AUTH_ERROR_CODES:
        return False, summary
    if status_code >= 500:
        return True, summary
    return False, summary


async def _send_once(client: httpx.AsyncClient, item: QueuedItem) -> tuple[bool, int | None, str | None, bool]:
    """Return (delivered, status_code, error, retryable)."""

    target = getattr(item, "target", "broker") or "broker"

    if target == "graph_api":
        token = current_page_access_token()
        if not token:
            return False, None, "page access token missing", False
        url = f"{_GRAPH_API_BASE}?access_token={token}"
        reply_text = (
            item.payload.get("reply", {}).get("text") if isinstance(item.payload, dict) else None
        )
        recipient_id = item.payload.get("user_id") if isinstance(item.payload, dict) else None
        if not reply_text or not recipient_id:
            return False, None, "queued graph_api item missing reply.text or user_id", False
        body = {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {"text": reply_text},
        }
        try:
            response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            return False, None, f"transport: {exc.__class__.__name__}: {exc}", True
        if response.status_code < 400:
            return True, response.status_code, None, False
        try:
            err_body = response.json()
        except ValueError:
            err_body = None
        retryable, summary = _classify_graph_error(response.status_code, err_body)
        return False, response.status_code, summary, retryable

    # broker target
    try:
        response = await client.post(item.target_url, json=item.payload)
    except httpx.HTTPError as exc:
        return False, None, f"transport: {exc.__class__.__name__}: {exc}", True

    if response.status_code < 400:
        return True, response.status_code, None, False

    retryable = response.status_code >= 500
    snippet = (response.text or "")[:200]
    return False, response.status_code, f"http {response.status_code}: {snippet}", retryable


async def _process_batch(
    items: list[QueuedItem],
    *,
    queue: RedisOutboundQueue,
    client_factory,
) -> dict[str, int]:
    """Drive the retry loop for one batch. Returns counters for observability."""

    counters = {"delivered": 0, "requeued": 0, "dead_lettered": 0}
    backoff_intervals = settings.outbound_backoff_seconds()
    max_attempts = settings.outbound_max_attempts

    async with client_factory() as client:
        for item in items:
            delivered, status, error, retryable = await _send_once(client, item)

            if delivered:
                _log.info(
                    "outbound retried delivery ok correlation_id=%s attempt=%d status=%s",
                    item.correlation_id, item.attempts + 1, status,
                )
                counters["delivered"] += 1
                continue

            # Failure path
            attempted = QueuedItem(
                correlation_id=item.correlation_id,
                target_url=item.target_url,
                payload=item.payload,
                attempts=item.attempts + 1,
                first_failed_at=item.first_failed_at or _now_epoch(),
                last_error=error,
                target=getattr(item, "target", "broker") or "broker",
            )

            if not retryable or attempted.attempts >= max_attempts:
                await queue.dead_letter(attempted)
                counters["dead_lettered"] += 1
                continue

            backoff = backoff_intervals[
                min(attempted.attempts - 1, len(backoff_intervals) - 1)
            ]
            scheduled = QueuedItem(
                correlation_id=attempted.correlation_id,
                target_url=attempted.target_url,
                payload=attempted.payload,
                attempts=attempted.attempts,
                next_attempt_ts=_now_epoch() + backoff,
                first_failed_at=attempted.first_failed_at,
                last_error=attempted.last_error,
                target=attempted.target,
            )
            await queue.requeue(scheduled)
            counters["requeued"] += 1

    return counters


async def run_forever(
    *,
    stop_event: asyncio.Event | None = None,
    queue: RedisOutboundQueue | None = None,
    client_factory=None,
    poll_seconds: float | None = None,
    iteration_limit: int | None = None,
) -> None:
    """Drain loop. Exits when ``stop_event`` is set OR ``iteration_limit`` hit
    (the latter for testability)."""

    stop_event = stop_event or asyncio.Event()
    queue = queue or get_queue()
    poll = poll_seconds if poll_seconds is not None else settings.outbound_worker_poll_seconds
    client_factory = client_factory or (
        lambda: httpx.AsyncClient(timeout=settings.outbound_send_timeout_seconds)
    )

    _log.info(
        "outbound worker started poll=%.1fs batch=%d max_attempts=%d",
        poll, settings.outbound_worker_batch_size, settings.outbound_max_attempts,
    )

    iterations = 0
    while not stop_event.is_set():
        iterations += 1
        items = await queue.due_items(now=_now_epoch())
        if items:
            counters = await _process_batch(
                items, queue=queue, client_factory=client_factory
            )
            _log.info(
                "outbound batch drained delivered=%d requeued=%d dead_lettered=%d",
                counters["delivered"],
                counters["requeued"],
                counters["dead_lettered"],
            )

        if iteration_limit is not None and iterations >= iteration_limit:
            break

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
        except asyncio.TimeoutError:
            continue

    _log.info("outbound worker stopped")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async def _runner() -> None:
        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)
        await run_forever(stop_event=stop_event)

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:  # pragma: no cover
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
