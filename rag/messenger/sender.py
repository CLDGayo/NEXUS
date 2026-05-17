"""Phase 6 outbound dispatcher.

Tries to POST the reply to the n8n / Make webhook immediately with a short
timeout. On any retryable failure (5xx / transport error / timeout), the
payload is enqueued to ``RedisOutboundQueue`` so the worker picks it up
later. On a 4xx (client error) the item moves straight to the DLQ — a
malformed body or wrong URL will not succeed on retry.

The webhook handler awaits ``dispatch(...)`` directly. Because the optimistic
POST has a hard 5s ceiling and the queue enqueue is sub-millisecond, this
stays within a typical Messenger ack budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from rag.config import settings
from rag.messenger.payloads import OutboundPayload
from rag.messenger.queue import QueuedItem, RedisOutboundQueue, get_queue
from rag.observability.decorators import traced

_log = logging.getLogger(__name__)


class OutboundError(RuntimeError):
    """Raised when the outbound POST cannot succeed under retry rules."""


SendOutcome = Literal["delivered", "queued", "dead_letter", "skipped"]


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    status_code: int | None
    attempts: int
    error: str | None = None


def _retryable_status(status_code: int) -> bool:
    """5xx are retryable; 4xx are client errors and shouldn't retry."""

    return status_code >= 500


class OutboundSender:
    """Thin client around httpx + the Redis retry queue."""

    def __init__(
        self,
        *,
        queue: RedisOutboundQueue | None = None,
        client_factory=None,
    ) -> None:
        self._queue = queue
        self._client_factory = client_factory or self._default_client_factory

    @staticmethod
    def _default_client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=settings.outbound_send_timeout_seconds)

    @property
    def queue(self) -> RedisOutboundQueue:
        if self._queue is None:
            self._queue = get_queue()
        return self._queue

    @traced("outbound.dispatch", kind="webhook")
    async def dispatch(
        self,
        payload: OutboundPayload,
        *,
        target_url: str | None = None,
    ) -> SendResult:
        """Send the payload now or schedule retries.

        ``target_url`` overrides ``settings.make_webhook_url``. If neither
        is set, ``SendResult(outcome="skipped")`` is returned — outbound
        dispatch is opt-in.
        """

        url = target_url or settings.make_webhook_url
        if not url:
            return SendResult(outcome="skipped", status_code=None, attempts=0)

        body = payload.model_dump(mode="json")

        try:
            async with self._client_factory() as client:
                response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            return await self._on_failure(
                payload=payload,
                target_url=url,
                attempts_so_far=0,
                error=f"transport: {exc.__class__.__name__}: {exc}",
                retryable=True,
            )

        if response.status_code < 400:
            _log.info(
                "outbound delivered correlation_id=%s status=%d",
                payload.correlation_id, response.status_code,
            )
            return SendResult(
                outcome="delivered",
                status_code=response.status_code,
                attempts=1,
            )

        # Non-2xx
        body_snippet = (response.text or "")[:200]
        retryable = _retryable_status(response.status_code)
        return await self._on_failure(
            payload=payload,
            target_url=url,
            attempts_so_far=0,
            error=f"http {response.status_code}: {body_snippet}",
            retryable=retryable,
            status_code=response.status_code,
        )

    async def _on_failure(
        self,
        *,
        payload: OutboundPayload,
        target_url: str,
        attempts_so_far: int,
        error: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> SendResult:
        """Enqueue for retry OR dead-letter. ``attempts_so_far`` is the
        count BEFORE this failure (0 for the optimistic synchronous send).
        """

        item = QueuedItem(
            correlation_id=payload.correlation_id,
            target_url=target_url,
            payload=payload.model_dump(mode="json"),
            attempts=attempts_so_far + 1,
            last_error=error,
        )

        if not retryable:
            await self.queue.dead_letter(item)
            _log.warning(
                "outbound client error → DLQ correlation_id=%s status=%s err=%s",
                payload.correlation_id, status_code, error,
            )
            return SendResult(
                outcome="dead_letter",
                status_code=status_code,
                attempts=item.attempts,
                error=error,
            )

        # Retryable — pick first backoff interval.
        backoff_intervals = settings.outbound_backoff_seconds()
        max_attempts = settings.outbound_max_attempts

        if item.attempts >= max_attempts:
            await self.queue.dead_letter(item)
            return SendResult(
                outcome="dead_letter",
                status_code=status_code,
                attempts=item.attempts,
                error=error,
            )

        backoff = backoff_intervals[min(item.attempts - 1, len(backoff_intervals) - 1)]
        import time

        item = item.with_attempt(error=error, now=int(time.time()), backoff_seconds=backoff)
        # NOTE: ``with_attempt`` re-increments .attempts — undo the optimistic
        # bump so we don't double-count when the worker drives the loop.
        item = QueuedItem(
            correlation_id=item.correlation_id,
            target_url=item.target_url,
            payload=item.payload,
            attempts=item.attempts - 1,
            next_attempt_ts=item.next_attempt_ts,
            first_failed_at=item.first_failed_at,
            last_error=item.last_error,
        )
        await self.queue.enqueue(item)
        _log.warning(
            "outbound queued for retry correlation_id=%s attempts=%d next_in=%ds err=%s",
            payload.correlation_id, item.attempts, backoff, error,
        )
        return SendResult(
            outcome="queued",
            status_code=status_code,
            attempts=item.attempts,
            error=error,
        )


_sender_singleton: OutboundSender | None = None


def get_sender() -> OutboundSender:
    global _sender_singleton
    if _sender_singleton is None:
        _sender_singleton = OutboundSender()
    return _sender_singleton


def set_sender(sender: OutboundSender | None) -> None:
    """Test hook."""

    global _sender_singleton
    _sender_singleton = sender
