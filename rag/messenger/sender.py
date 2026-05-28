"""Outbound dispatcher — broker (n8n / Make) OR direct Graph API.

Phase 6 introduced this module as a thin wrapper around the n8n / Make
broker webhook with Redis-backed retry. Phase 12 extends it with a
second target — Facebook Graph API ``/v21.0/me/messages`` — so the
backend can ship LangGraph replies directly to Messenger users without
the broker hop. The page access token is read live from
:mod:`rag.messenger_overlay` on every send, so a token rotated in the
admin UI is picked up on the next call (no restart, no cache).

The retry queue is shared: failed sends to either target land in the
same Redis sorted set and are drained by the same worker process. The
``target`` field on :class:`QueuedItem` tells the worker which transport
to drive on retry.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from rag.config import settings
from rag.messenger.payloads import OutboundPayload, ProductCarouselBlock
from rag.messenger.queue import QueuedItem, RedisOutboundQueue, get_queue
from rag.messenger_overlay import current_page_access_token
from rag.observability.decorators import traced

_log = logging.getLogger(__name__)


_GRAPH_API_BASE = "https://graph.facebook.com/v21.0/me/messages"
# Facebook error codes that mean "the token is gone / page is gone".
# Source: Meta error reference.
_FB_AUTH_ERROR_CODES: frozenset[int] = frozenset({190, 100, 200, 10})
# Rate-limit subcodes — retryable.
_FB_RATE_LIMIT_CODES: frozenset[int] = frozenset({4, 17, 613})


class OutboundError(RuntimeError):
    """Raised when the outbound POST cannot succeed under retry rules."""


class MessengerTokenMissing(RuntimeError):
    """No page access token is configured (overlay + env both empty)."""


OutboundTarget = Literal["broker", "graph_api"]
SendOutcome = Literal["delivered", "queued", "dead_letter", "skipped"]


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    status_code: int | None
    attempts: int
    error: str | None = None
    target: OutboundTarget = "broker"


def _retryable_status(status_code: int) -> bool:
    """5xx are retryable; 4xx are client errors and shouldn't retry."""

    return status_code >= 500


def _classify_graph_error(status_code: int, body: dict | None) -> tuple[bool, str]:
    """Return ``(retryable, error_summary)`` for a Graph API failure.

    Token / permission errors are *not* retryable — the same token will
    keep failing until rotated in the admin UI. Rate-limit errors are
    retryable. 5xx is retryable. Everything else 4xx is non-retryable.
    """

    err = (body or {}).get("error") if isinstance(body, dict) else None
    code = int((err or {}).get("code", 0) or 0)
    subcode = int((err or {}).get("error_subcode", 0) or 0)
    msg = str((err or {}).get("message") or "")[:200]
    summary = f"http {status_code} code={code} subcode={subcode}: {msg}".strip()

    # Rate-limit precedence over auth: FB uses code=100 with subcode=613
    # for "Calls to this api have exceeded the rate limit", which would
    # otherwise be misread as auth (code 100 is also "Invalid parameter").
    if code in _FB_RATE_LIMIT_CODES or subcode in _FB_RATE_LIMIT_CODES:
        return True, summary
    if code in _FB_AUTH_ERROR_CODES or subcode in _FB_AUTH_ERROR_CODES:
        return False, summary
    if status_code >= 500:
        return True, summary
    return False, summary


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
        target: OutboundTarget = "broker",
    ) -> SendResult:
        """Send the payload now or schedule retries.

        ``target="broker"`` (default) → POST to ``target_url`` or
        ``settings.make_webhook_url``. Returns ``skipped`` when neither
        is set.

        ``target="graph_api"`` → call Facebook Graph API
        ``/v21.0/me/messages``. ``target_url`` is ignored; the URL is
        built from ``current_page_access_token()`` at send time.
        """

        if target == "graph_api":
            return await self._dispatch_graph_api(payload)
        return await self._dispatch_broker(payload, target_url=target_url)

    # ------------------------------------------------------------------
    # Broker target (n8n / Make webhook)
    # ------------------------------------------------------------------

    async def _dispatch_broker(
        self,
        payload: OutboundPayload,
        *,
        target_url: str | None,
    ) -> SendResult:
        url = target_url or settings.make_webhook_url
        if not url:
            return SendResult(
                outcome="skipped", status_code=None, attempts=0, target="broker"
            )

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
                target="broker",
            )

        if response.status_code < 400:
            _log.info(
                "outbound.broker delivered correlation_id=%s status=%d",
                payload.correlation_id,
                response.status_code,
            )
            return SendResult(
                outcome="delivered",
                status_code=response.status_code,
                attempts=1,
                target="broker",
            )

        body_snippet = (response.text or "")[:200]
        retryable = _retryable_status(response.status_code)
        return await self._on_failure(
            payload=payload,
            target_url=url,
            attempts_so_far=0,
            error=f"http {response.status_code}: {body_snippet}",
            retryable=retryable,
            status_code=response.status_code,
            target="broker",
        )

    # ------------------------------------------------------------------
    # Graph API target (direct to Meta)
    # ------------------------------------------------------------------

    async def _dispatch_graph_api(
        self,
        payload: OutboundPayload,
    ) -> SendResult:
        token = current_page_access_token()
        if not token:
            _log.error(
                "outbound.graph_api: page access token missing correlation_id=%s",
                payload.correlation_id,
            )
            return SendResult(
                outcome="dead_letter",
                status_code=None,
                attempts=1,
                error="page access token missing",
                target="graph_api",
            )

        url = f"{_GRAPH_API_BASE}?access_token={token}"
        bodies = self._graph_message_bodies(payload)
        if not bodies:
            _log.error(
                "outbound.graph_api: empty reply correlation_id=%s",
                payload.correlation_id,
            )
            return SendResult(
                outcome="dead_letter",
                status_code=None,
                attempts=1,
                error="empty reply (no text, no carousel)",
                target="graph_api",
            )

        last_status: int | None = None
        for graph_body in bodies:
            try:
                async with self._client_factory() as client:
                    response = await client.post(url, json=graph_body)
            except httpx.HTTPError as exc:
                return await self._on_failure(
                    payload=payload,
                    target_url=_GRAPH_API_BASE,
                    attempts_so_far=0,
                    error=f"transport: {exc.__class__.__name__}: {exc}",
                    retryable=True,
                    target="graph_api",
                )

            if response.status_code >= 400:
                try:
                    err_body = response.json()
                except ValueError:
                    err_body = None
                retryable, summary = _classify_graph_error(
                    response.status_code, err_body
                )
                _log.warning(
                    "outbound.graph_api error correlation_id=%s retryable=%s %s",
                    payload.correlation_id,
                    retryable,
                    summary,
                )
                return await self._on_failure(
                    payload=payload,
                    target_url=_GRAPH_API_BASE,
                    attempts_so_far=0,
                    error=summary,
                    retryable=retryable,
                    status_code=response.status_code,
                    target="graph_api",
                )
            last_status = response.status_code

        _log.info(
            "outbound.graph_api delivered correlation_id=%s status=%s "
            "messages=%d token_tail=%s",
            payload.correlation_id,
            last_status,
            len(bodies),
            token[-4:] if len(token) >= 4 else "????",
        )
        return SendResult(
            outcome="delivered",
            status_code=last_status,
            attempts=1,
            target="graph_api",
        )

    # ------------------------------------------------------------------
    # Graph API body composition
    # ------------------------------------------------------------------

    def _graph_message_bodies(self, payload: OutboundPayload) -> list[dict]:
        """Build the ordered list of Send API bodies for this reply.

        Phase 32 — when ``reply.carousel`` is set the carousel goes out
        FIRST (so the cards land at the top of the thread), then the
        optional preamble text follows. Pure-text replies skip the
        carousel and produce a single body matching the pre-Phase-32
        shape.
        """
        bodies: list[dict] = []
        reply = payload.reply
        recipient_id = payload.user_id

        if reply.carousel is not None:
            bodies.append(
                self._format_generic_template(reply.carousel, recipient_id)
            )

        text = reply.text or ""
        # Phase 18 — strip [\d+] citation brackets from Messenger outbound
        # only. Guardrail pipeline + SPA SSE stream still see the cited
        # answer.
        clean_text = re.sub(r"\[\d+\]", "", text).strip()
        if clean_text:
            bodies.append(
                {
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": {"text": clean_text},
                }
            )
        return bodies

    @staticmethod
    def _format_generic_template(
        carousel: ProductCarouselBlock, recipient_id: str
    ) -> dict:
        """Translate a ProductCarouselBlock into the Send API Generic Template body."""
        return {
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            el.model_dump(mode="json", exclude_none=True)
                            for el in carousel.elements
                        ],
                    },
                }
            },
        }

    # ------------------------------------------------------------------
    # Failure path (shared)
    # ------------------------------------------------------------------

    async def _on_failure(
        self,
        *,
        payload: OutboundPayload,
        target_url: str,
        attempts_so_far: int,
        error: str,
        retryable: bool,
        status_code: int | None = None,
        target: OutboundTarget = "broker",
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
            target=target,
        )

        if not retryable:
            await self.queue.dead_letter(item)
            _log.warning(
                "outbound client error → DLQ correlation_id=%s target=%s status=%s err=%s",
                payload.correlation_id,
                target,
                status_code,
                error,
            )
            return SendResult(
                outcome="dead_letter",
                status_code=status_code,
                attempts=item.attempts,
                error=error,
                target=target,
            )

        backoff_intervals = settings.outbound_backoff_seconds()
        max_attempts = settings.outbound_max_attempts

        if item.attempts >= max_attempts:
            await self.queue.dead_letter(item)
            return SendResult(
                outcome="dead_letter",
                status_code=status_code,
                attempts=item.attempts,
                error=error,
                target=target,
            )

        backoff = backoff_intervals[min(item.attempts - 1, len(backoff_intervals) - 1)]
        scheduled = QueuedItem(
            correlation_id=item.correlation_id,
            target_url=item.target_url,
            payload=item.payload,
            attempts=item.attempts,
            next_attempt_ts=int(time.time()) + backoff,
            first_failed_at=item.first_failed_at or int(time.time()),
            last_error=error,
            target=item.target,
        )
        await self.queue.enqueue(scheduled)
        _log.warning(
            "outbound queued for retry correlation_id=%s target=%s attempts=%d next_in=%ds err=%s",
            payload.correlation_id,
            target,
            scheduled.attempts,
            backoff,
            error,
        )
        return SendResult(
            outcome="queued",
            status_code=status_code,
            attempts=scheduled.attempts,
            error=error,
            target=target,
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
