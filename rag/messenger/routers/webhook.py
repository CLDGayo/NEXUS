"""Messenger webhook router — Phase 6 broker path + Phase 12 direct path.

Two ingress styles coexist on this router:

* **Direct from Meta** (``GET /messenger/inbound`` + ``POST
  /messenger/inbound``). Phase 12. Meta calls our public webhook
  directly: GET for the one-time verify-token handshake, POST for every
  inbound message event signed with ``X-Hub-Signature-256``. The POST
  handler returns ``200 EVENT_RECEIVED`` synchronously (Meta's 20 s
  webhook timeout) and dispatches the LangGraph cortex in the
  background, then sends the reply directly to
  ``graph.facebook.com/v21.0/me/messages`` using the dynamic page
  access token from :mod:`rag.messenger_overlay`.

* **From the n8n / Make orchestrator** (``POST
  /messenger/orchestrator``). Phase 6. The orchestrator normalizes
  Meta's raw payload, authenticates with ``X-Webhook-Api-Key``, and
  receives the reply in the synchronous ack body (or asks us to POST it
  to an outbound webhook). Preserved for the Phase 11 broker workflow;
  one URL change on the n8n side moves it off ``/inbound``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from opentelemetry import trace

from rag.config import settings
from rag.guardrails.groundedness import abstention_text
from rag.messenger.idempotency import check_idempotency
from rag.messenger.payloads import build_outbound_payload
from rag.messenger.pii import scrub
from rag.messenger.ratelimit import enforce_rate_limit
from rag.messenger.schemas import (
    InboundAck,
    InboundMessage,
    OptOutAck,
    OptOutRequest,
)
from rag.messenger.security import (
    require_webhook_api_key,
    verify_meta_signature,
)
from rag.messenger.sender import OutboundSender, SendResult, get_sender
from rag.messenger_overlay import current_verify_token

_log = logging.getLogger(__name__)

router = APIRouter(tags=["messenger-webhook"])


# ---------------------------------------------------------------------------
# Graph runner dependency
# ---------------------------------------------------------------------------

GraphRunner = Callable[[InboundMessage, str], Awaitable[dict]]


async def _real_graph_runner(payload: InboundMessage, correlation_id: str) -> dict:
    """Default runner — calls the live LangGraph cortex."""

    # Imported lazily so test environments that override this dependency
    # never trigger the heavy orchestrator import chain.
    from rag.orchestrator.graph import run_graph

    return await run_graph(
        query=payload.message_text,
        thread_key=payload.user_id,
        correlation_id=correlation_id,
        surface="messenger",
    )


async def get_graph_runner() -> GraphRunner:
    """FastAPI dependency. Override in tests via
    ``app.dependency_overrides[get_graph_runner]``."""

    return _real_graph_runner


# ---------------------------------------------------------------------------
# Outbound dispatcher dependency
# ---------------------------------------------------------------------------

async def get_outbound_sender() -> OutboundSender:
    """FastAPI dependency. Tests override via dependency_overrides."""

    return get_sender()


# ---------------------------------------------------------------------------
# Background-task scheduler — overridable in tests so the LangGraph step
# can be awaited deterministically.
# ---------------------------------------------------------------------------

EventScheduler = Callable[[Awaitable[None]], None]


def _default_scheduler(coro: Awaitable[None]) -> None:
    asyncio.create_task(coro)  # type: ignore[arg-type]


_scheduler: EventScheduler = _default_scheduler


def set_event_scheduler(scheduler: EventScheduler | None) -> None:
    """Test hook. Pass ``None`` to restore the default ``asyncio.create_task``."""

    global _scheduler
    _scheduler = scheduler if scheduler is not None else _default_scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _correlation_id(provided: str | None) -> str:
    return provided or f"corr_{uuid.uuid4().hex[:16]}"


def _now_epoch() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def _should_dispatch_outbound(payload: InboundMessage) -> str | None:
    """Resolve the outbound URL or return None to skip."""

    if payload.outbound_url:
        return payload.outbound_url
    if settings.outbound_dispatch_enabled and settings.make_webhook_url:
        return settings.make_webhook_url
    return None


# ---------------------------------------------------------------------------
# Phase 12 — Meta direct endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/messenger/inbound",
    summary="Meta webhook handshake (GET).",
)
async def messenger_handshake(request: Request) -> PlainTextResponse:
    """Verify-token handshake. Meta calls this once when the webhook URL
    is registered (and any time the operator clicks "Verify and save"
    in the App Dashboard).

    The verify token is compared against the live overlay value from
    :func:`rag.messenger_overlay.current_verify_token` — rotating it in
    the admin UI takes effect on the next handshake without a restart.
    """

    params = request.query_params
    mode = params.get("hub.mode")
    challenge = params.get("hub.challenge")
    provided_token = params.get("hub.verify_token")

    expected_token = current_verify_token()
    if not expected_token:
        _log.warning("messenger.handshake.no_verify_token_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verify token not configured",
        )

    if mode != "subscribe":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="mode")

    import hmac as _hmac

    if not provided_token or not _hmac.compare_digest(provided_token, expected_token):
        _log.warning("messenger.handshake.token_mismatch")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verify token")

    if not challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="challenge")

    _log.info("messenger.handshake.ok")
    return PlainTextResponse(challenge)


@router.post(
    "/messenger/inbound",
    status_code=status.HTTP_200_OK,
    summary="Inbound webhook from Meta (signed raw payload).",
)
async def messenger_inbound_direct(
    request: Request,
    runner: GraphRunner = Depends(get_graph_runner),
    sender: OutboundSender = Depends(get_outbound_sender),
) -> PlainTextResponse:
    """Handle a signed inbound webhook event from Meta.

    The request body is verified against ``X-Hub-Signature-256`` using
    the Facebook App Secret, then parsed as ``{"object": "page",
    "entry": [...]}``. Each ``messaging`` event with text is scheduled
    as a background task so this handler can return ``200
    EVENT_RECEIVED`` within Meta's 20 s webhook timeout — LangGraph and
    the outbound Graph API call complete asynchronously.
    """

    raw = await request.body()
    verify_meta_signature(raw, request.headers.get("X-Hub-Signature-256"))

    try:
        envelope = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log.warning("messenger.inbound.bad_json err=%s", exc)
        # Still return 200: returning 4xx makes Meta retry, which only
        # spams malformed deliveries. Log and move on.
        return PlainTextResponse("EVENT_RECEIVED")

    if envelope.get("object") != "page":
        _log.info("messenger.inbound.ignored_object obj=%s", envelope.get("object"))
        return PlainTextResponse("EVENT_RECEIVED")

    scheduled = 0
    for entry in envelope.get("entry") or []:
        page_id = str(entry.get("id") or "")
        for event in entry.get("messaging") or []:
            sender_id = str(((event.get("sender") or {}).get("id")) or "")
            message = event.get("message") or {}
            mid = str(message.get("mid") or "")
            text = message.get("text")
            if not sender_id or not text or not isinstance(text, str):
                continue
            if message.get("is_echo"):
                # Our own outbound deliveries echo back — never reply to them.
                continue

            inbound = InboundMessage(
                user_id=sender_id,
                message_text=text,
                timestamp=_now_epoch(),
                channel="messenger",
                page_id=page_id or None,
                correlation_id=mid or None,
            )
            _scheduler(
                _handle_messenger_event(
                    inbound=inbound,
                    runner=runner,
                    sender=sender,
                )
            )
            scheduled += 1

    _log.info("messenger.inbound.accepted scheduled=%d", scheduled)
    return PlainTextResponse("EVENT_RECEIVED")


async def _handle_messenger_event(
    *,
    inbound: InboundMessage,
    runner: GraphRunner,
    sender: OutboundSender,
) -> None:
    """Background task: run LangGraph + send reply directly to Meta."""

    started = time.perf_counter()
    correlation_id = _correlation_id(inbound.correlation_id)

    try:
        await enforce_rate_limit(inbound)
    except HTTPException as exc:
        _log.info(
            "messenger.event.rate_limited user=%s status=%d",
            inbound.user_id,
            exc.status_code,
        )
        return

    try:
        verdict = await check_idempotency(inbound)
    except Exception as exc:  # noqa: BLE001 — never let Redis flake kill the reply
        _log.warning("messenger.event.idempotency_unavailable err=%s", exc)
        verdict = None

    if verdict is not None and verdict.duplicate:
        _log.info(
            "messenger.event.duplicate correlation_id=%s mid=%s",
            correlation_id,
            inbound.correlation_id,
        )
        return

    scrub_result = scrub(inbound.message_text)
    if scrub_result.redactions:
        current_span = trace.get_current_span()
        if current_span is not None and current_span.is_recording():
            current_span.add_event(
                "pii.scrubbed",
                attributes={
                    f"pii.count.{kind.lower()}": count
                    for kind, count in scrub_result.counts_by_kind.items()
                },
            )
        inbound = inbound.model_copy(
            update={"message_text": scrub_result.scrubbed_text}
        )

    graph_result: dict[str, Any] = {}
    try:
        graph_result = await runner(inbound, correlation_id)
        reply_text = (graph_result.get("answer") or "").strip() or abstention_text()
    except Exception as exc:
        _log.exception(
            "graph dispatch failed",
            extra={"correlation_id": correlation_id, "err": str(exc)},
        )
        reply_text = abstention_text()
        graph_result = {"abstained": True, "requires_human_handover": True}

    try:
        outbound_payload = build_outbound_payload(
            inbound=inbound,
            correlation_id=correlation_id,
            reply_text=reply_text,
            graph_result=graph_result,
        )
        result: SendResult = await sender.dispatch(
            outbound_payload, target="graph_api"
        )
        _log.info(
            "messenger.event.dispatched outcome=%s status=%s attempts=%d "
            "elapsed_ms=%d correlation_id=%s",
            result.outcome,
            result.status_code,
            result.attempts,
            int((time.perf_counter() - started) * 1000),
            correlation_id,
        )
    except Exception as exc:
        _log.exception(
            "messenger.event.dispatch_crashed correlation_id=%s err=%s",
            correlation_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Phase 6 — Orchestrator broker endpoint (n8n / Make)
# ---------------------------------------------------------------------------

@router.post(
    "/messenger/orchestrator",
    response_model=InboundAck,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_webhook_api_key)],
    summary="Receive an inbound user message forwarded by the orchestrator.",
)
async def messenger_inbound_orchestrator(
    payload: InboundMessage,
    runner: GraphRunner = Depends(get_graph_runner),
    sender: OutboundSender = Depends(get_outbound_sender),
) -> InboundAck:
    """Broker path. Synchronous: returns the reply in the ack body, and
    optionally POSTs it to an outbound webhook with retry.

    This is the Phase 6 / Phase 11 entrypoint, preserved at a stable URL
    so existing n8n workflows keep working after a one-line URL swap
    away from the (now Meta-direct) ``/messenger/inbound``.
    """

    # Note: not @traced — FastAPIInstrumentor already creates a span per
    # request which serves as the root for the orchestrator's nested
    # spans. Layering @traced on top broke Pydantic body extraction in
    # FastAPI's signature inspector.
    started = time.perf_counter()
    correlation_id = _correlation_id(payload.correlation_id)

    # Order matters. Rate-limit BEFORE idempotency so a flood of
    # duplicate retries still counts against the spammer's budget. PII
    # scrub BEFORE the runner so nested spans + Langfuse only see the
    # redacted text.
    await enforce_rate_limit(payload)

    verdict = await check_idempotency(payload)
    if verdict.duplicate:
        return InboundAck(
            status="duplicate",
            correlation_id=correlation_id,
            reply_text=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            received_at=_now_epoch(),
        )

    scrub_result = scrub(payload.message_text)
    if scrub_result.redactions:
        current_span = trace.get_current_span()
        if current_span is not None and current_span.is_recording():
            current_span.add_event(
                "pii.scrubbed",
                attributes={
                    f"pii.count.{kind.lower()}": count
                    for kind, count in scrub_result.counts_by_kind.items()
                },
            )
        payload = payload.model_copy(
            update={"message_text": scrub_result.scrubbed_text}
        )

    graph_result: dict = {}
    try:
        graph_result = await runner(payload, correlation_id)
        reply_text = (graph_result.get("answer") or "").strip() or abstention_text()
    except Exception as exc:
        _log.exception(
            "graph dispatch failed",
            extra={"correlation_id": correlation_id, "err": str(exc)},
        )
        reply_text = abstention_text()
        graph_result = {"abstained": True, "requires_human_handover": True}

    # Optional broker outbound dispatch with retry safety net.
    outbound_url = _should_dispatch_outbound(payload)
    if outbound_url:
        try:
            outbound_payload = build_outbound_payload(
                inbound=payload,
                correlation_id=correlation_id,
                reply_text=reply_text,
                graph_result=graph_result,
            )
            send_result: SendResult = await sender.dispatch(
                outbound_payload, target_url=outbound_url, target="broker"
            )
            _log.info(
                "outbound dispatch outcome=%s status=%s attempts=%d corr=%s",
                send_result.outcome,
                send_result.status_code,
                send_result.attempts,
                correlation_id,
            )
        except Exception as exc:
            # Sender already wraps Redis failures — but a programming bug
            # here must never break the sync ack.
            _log.exception(
                "outbound dispatcher crashed; sync ack still returned",
                extra={"correlation_id": correlation_id, "err": str(exc)},
            )

    return InboundAck(
        status="accepted",
        correlation_id=correlation_id,
        reply_text=reply_text,
        latency_ms=int((time.perf_counter() - started) * 1000),
        received_at=_now_epoch(),
    )


@router.post(
    "/messenger/optout",
    response_model=OptOutAck,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_webhook_api_key)],
    summary="Acknowledge a user data-deletion request (Meta App Review requirement).",
)
async def messenger_optout(payload: OptOutRequest) -> OptOutAck:
    return OptOutAck(
        status="accepted",
        correlation_id=_correlation_id(payload.correlation_id),
        received_at=_now_epoch(),
    )
