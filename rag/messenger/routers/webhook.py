"""Phase 3 webhook router.

Receives inbound messages from the orchestrator (n8n / Make), validates the
shape against :class:`InboundMessage`, dispatches into the LangGraph cortex,
and returns the generated reply.

The graph runner is injected via FastAPI ``Depends`` so unit tests can
override it without monkey-patching module globals.

Phase 8 will additionally enqueue the LangGraph run to a background worker
and respond ``202`` immediately, plus push the outbound message via the
Facebook Graph API. Phase 3 keeps the call synchronous for simplicity.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from rag.guardrails.groundedness import abstention_text
from rag.messenger.schemas import (
    InboundAck,
    InboundMessage,
    OptOutAck,
    OptOutRequest,
)
from rag.messenger.security import require_webhook_api_key
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
# Helpers
# ---------------------------------------------------------------------------

def _correlation_id(provided: str | None) -> str:
    return provided or f"corr_{uuid.uuid4().hex[:16]}"


def _now_epoch() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


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
@traced("webhook.messenger.inbound", kind="webhook")
async def messenger_inbound(
    payload: InboundMessage,
    runner: GraphRunner = Depends(get_graph_runner),
) -> InboundAck:
    started = time.perf_counter()
    correlation_id = _correlation_id(payload.correlation_id)

    try:
        result = await runner(payload, correlation_id)
        # `or abstention_text()` is not enough — a whitespace-only string is
        # truthy in Python. Strip first, then fall back.
        reply_text = (result.get("answer") or "").strip() or abstention_text()
    except Exception as exc:
        _log.exception(
            "graph dispatch failed",
            extra={"correlation_id": correlation_id, "err": str(exc)},
        )
        reply_text = abstention_text()

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
@traced("webhook.messenger.optout", kind="webhook")
async def messenger_optout(payload: OptOutRequest) -> OptOutAck:
    # Phase 6+ will purge per-user state from Postgres + Redis. Phase 3 acks.
    return OptOutAck(
        status="accepted",
        correlation_id=_correlation_id(payload.correlation_id),
        received_at=_now_epoch(),
    )
