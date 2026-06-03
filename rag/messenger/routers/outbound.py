"""Phase 40 — Proactive Cart Recovery outbound webhook router.

Exposes ``POST /outbound/cart-recovery`` to receive n8n abandoned-cart
payloads and dispatch a warm, empathetic Seina recovery message to the
customer's Messenger thread via the Meta Graph API.

Auth: ``X-Webhook-Api-Key`` header — same shared secret as the inbound
broker endpoint (``require_webhook_api_key`` dependency).

The endpoint returns HTTP 202 immediately. All graph invocation and
dispatch work happens inside ``_run_cart_recovery``, a background task
registered with the same ``_task_registry`` / ``_default_scheduler`` the
inbound router uses so in-flight recovery tasks drain cleanly on SIGTERM
alongside inbound tasks.

Four pre-flight safety gates run in strict sequential order before the
graph is invoked:
  1. Idempotency  — ``claim_cart_idempotency(cart_id)`` Redis NX EX 86400
  2. HITL         — ``is_bot_paused(psid)``
  3. 24h window + cold PSID — ``graph.aget_state`` snapshot check
  4. Thread lock  — ``acquire_thread_lock(psid)``
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AnyHttpUrl, BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from rag.database.engine import get_async_session, get_sessionmaker
from rag.messenger.hitl import is_bot_paused
from rag.messenger.idempotency import (
    acquire_thread_lock,
    claim_cart_idempotency,
    release_thread_lock,
)
from rag.messenger.routers.webhook import _default_scheduler
from rag.messenger.security import require_webhook_api_key
from rag.messenger.tenant_resolver import resolve_tenant_for_page
from rag.messenger_overlay import current_page_access_token
from rag.orchestrator.ai_settings import load_ai_settings
from rag.orchestrator.graph import get_graph, run_graph

_log = logging.getLogger(__name__)

router = APIRouter(tags=["messenger-outbound"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CartItem(BaseModel):
    name: str
    quantity: int
    price: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("CartItem.name must not be empty")
        return v

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("CartItem.quantity must be >= 1")
        return v


class CartRecoveryRequest(BaseModel):
    cart_id: str
    psid: str
    page_id: str
    cart_items: list[CartItem]
    checkout_url: AnyHttpUrl

    @field_validator("cart_id", "psid", "page_id")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be empty or whitespace-only")
        return v

    @field_validator("cart_items")
    @classmethod
    def at_least_one_item(cls, v: list[CartItem]) -> list[CartItem]:
        if not v:
            raise ValueError("cart_items must contain at least one item")
        return v


class CartRecoveryAck(BaseModel):
    status: str
    cart_id: str


# ---------------------------------------------------------------------------
# HTTP send helper
# ---------------------------------------------------------------------------


async def send_text_message(
    *,
    recipient_id: str,
    message: str,
    access_token: str,
    messaging_type: str = "RESPONSE",
) -> None:
    """POST a text message to the Meta Graph API.

    Uses a minimal httpx call — no Redis retry queue needed for the cart
    path. The idempotency gate + 24h window check together make retrying
    within the window moot; a token revocation is logged and the task ends.
    """

    url = "https://graph.facebook.com/v21.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
        "messaging_type": messaging_type,
    }
    params = {"access_token": access_token}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
    ) as client:
        resp = await client.post(url, json=payload, params=params)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Background task — the 4 Locks + graph + dispatch
# ---------------------------------------------------------------------------


async def _run_cart_recovery(
    payload: CartRecoveryRequest,
    tenant_slug: str,
) -> None:
    """Execute the 4-Lock pre-flight sequence, invoke the graph, and dispatch.

    All gates abort early on failure. After Lock 4 is acquired, every
    subsequent path goes through ``finally: release_thread_lock``.

    The idempotency key is set at Lock 1 even when later locks abort —
    this marks the cart_id as "processed this attempt". An n8n retry
    within 24h will correctly be deduplicated. A new ``cart_id`` is needed
    to trigger a fresh attempt.
    """

    # LOCK 1 — Idempotency
    idemp = await claim_cart_idempotency(payload.cart_id)
    if idemp.duplicate:
        _log.info("cart_recovery.duplicate cart_id=%s", payload.cart_id)
        return

    # LOCK 2 — HITL
    if await is_bot_paused(payload.psid):
        _log.info("cart_recovery.suppressed_hitl_active psid=%s", payload.psid)
        return

    # LOCK 3 — 24h window + cold PSID
    config: dict[str, Any] = {"configurable": {"thread_id": payload.psid}}
    graph = get_graph()
    try:
        snapshot = await graph.aget_state(config)
    except Exception as exc:  # noqa: BLE001
        _log.warning("cart_recovery.snapshot_failed psid=%s err=%s", payload.psid, exc)
        return  # fail closed

    if snapshot is None or not snapshot.values:
        _log.info("cart_recovery.cold_psid psid=%s", payload.psid)
        return  # no thread history — cold PSID

    history: list[dict[str, Any]] = list(snapshot.values.get("history") or [])
    last_user_ts: float | None = None
    for entry in reversed(history):
        if isinstance(entry, dict) and entry.get("role") == "user":
            ts = entry.get("timestamp")
            if isinstance(ts, (int, float)):
                last_user_ts = float(ts)
                break

    if last_user_ts is None:
        # History exists but no user turn with a timestamp — fail closed
        _log.info("cart_recovery.cold_psid psid=%s reason=no_user_ts", payload.psid)
        return

    age_s = time.time() - last_user_ts
    if age_s > 86400:
        _log.info(
            "cart_recovery.window_expired psid=%s age_s=%.0f",
            payload.psid,
            age_s,
        )
        return

    # LOCK 4 — Thread lock (serialize against concurrent inbound turn)
    lock_verdict = await acquire_thread_lock(payload.psid)
    if not lock_verdict.acquired:
        _log.info("cart_recovery.lock_contention psid=%s", payload.psid)
        return  # drop; the inbound task currently holds this thread

    try:
        # Build the cart context block for the recovery prompt
        cart_context: dict[str, Any] = {
            "cart_items": [
                f"{item.quantity}x {item.name}"
                + (f" ({item.price})" if item.price else "")
                for item in payload.cart_items
            ],
            "checkout_url": str(payload.checkout_url),
        }

        # Phase 45 — load ai_settings so generate_node can apply the tenant's
        # core_behavior overlay even on the outbound recovery surface.
        ai_settings_blob: dict | None = None
        if tenant_slug:
            sm = get_sessionmaker()
            async with sm() as db:
                ai_settings_blob = await load_ai_settings(tenant_slug, db)

        result = await run_graph(
            query="[outbound_recovery]",
            thread_key=payload.psid,
            correlation_id=f"cart_{payload.cart_id}",
            surface="outbound_recovery",
            tenant_id=tenant_slug,
            sender_id=payload.psid,
            cart_context=cart_context,
            ai_settings=ai_settings_blob,
        )

        reply_text = (result.get("answer") or "").strip()
        if not reply_text:
            _log.warning(
                "cart_recovery.empty_answer psid=%s cart_id=%s",
                payload.psid,
                payload.cart_id,
            )
            return

        token = current_page_access_token()
        if not token:
            _log.warning("cart_recovery.no_token psid=%s", payload.psid)
            return

        await send_text_message(
            recipient_id=payload.psid,
            message=reply_text,
            access_token=token,
            messaging_type="RESPONSE",
        )
        _log.info(
            "cart_recovery.dispatched psid=%s cart_id=%s outbound_type=cart_recovery",
            payload.psid,
            payload.cart_id,
        )

    except Exception as exc:  # noqa: BLE001
        _log.exception(
            "cart_recovery.task_failed psid=%s cart_id=%s err=%s",
            payload.psid,
            payload.cart_id,
            exc,
        )
    finally:
        await release_thread_lock(payload.psid)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/outbound/cart-recovery",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CartRecoveryAck,
    summary="Outbound cart-recovery trigger (Phase 40).",
)
async def cart_recovery(
    payload: CartRecoveryRequest,
    _auth: Annotated[None, Depends(require_webhook_api_key)],
    db: Annotated[AsyncSession, Depends(get_async_session)],
) -> CartRecoveryAck:
    """Receive an n8n abandoned-cart payload and dispatch a recovery message.

    Returns HTTP 202 immediately. The graph invocation + Meta dispatch runs
    in a background task registered with the shared ``_task_registry`` so
    in-flight tasks drain on SIGTERM alongside inbound messenger tasks.

    HTTP 422 if the ``page_id`` has no tenant mapping — the caller can
    debug this synchronously before the task runs.
    """

    tenant = await resolve_tenant_for_page(db, payload.page_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="no_tenant_mapping",
        )

    _default_scheduler(_run_cart_recovery(payload, tenant.slug))

    return CartRecoveryAck(status="accepted", cart_id=payload.cart_id)
