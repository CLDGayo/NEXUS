"""Phase 6 webhook router.

Receives inbound messages from the orchestrator (n8n / Make), validates the
shape against :class:`InboundMessage`, dispatches into the LangGraph cortex,
optionally POSTs the reply to a configured outbound webhook (with Redis-
backed retry), and returns the generated reply in the synchronous ack.

Two ingress patterns are simultaneously supported:

    1. **Sync clients** (e.g. n8n consuming the InboundAck response body
       directly) — get the reply text back in the ack and ignore the
       outbound POST.
    2. **Async clients** (any pipeline that wants webhook-style delivery
       with at-least-once guarantees) — set ``OUTBOUND_DISPATCH_ENABLED``
       or supply ``outbound_url`` per request; the reply is also POSTed
       to that URL, queued + retried on failure.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from rag.config import settings
from rag.guardrails.groundedness import abstention_text
from rag.messenger.payloads import build_outbound_payload
from rag.messenger.schemas import (
    InboundAck,
    InboundMessage,
    OptOutAck,
    OptOutRequest,
)
from rag.messenger.security import require_webhook_api_key
from rag.messenger.sender import OutboundSender, SendResult, get_sender
from rag.observability.decorators import traced

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
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/messenger/inbound",
    response_model=InboundAck,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_webhook_api_key)],
    summary="Receive an inbound user message forwarded by the orchestrator.",
)
async def messenger_inbound(
    payload: InboundMessage,
    runner: GraphRunner = Depends(get_graph_runner),
    sender: OutboundSender = Depends(get_outbound_sender),
) -> InboundAck:
    # Note: not @traced — FastAPIInstrumentor already creates a span per
    # request (``POST /webhook/messenger/inbound``) which serves as the
    # root for the orchestrator's nested spans. Layering @traced on top
    # broke Pydantic body extraction in FastAPI's signature inspector.
    started = time.perf_counter()
    correlation_id = _correlation_id(payload.correlation_id)

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

    # Phase 6 — optional outbound dispatch with retry safety net.
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
                outbound_payload, target_url=outbound_url
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
    # Phase 6+ will purge per-user state from Postgres + Redis. Phase 3 acks.
    return OptOutAck(
        status="accepted",
        correlation_id=_correlation_id(payload.correlation_id),
        received_at=_now_epoch(),
    )
