"""Phase 67 — Live Chat Inbox & Human Handoff REST API.

Manager-gated routes (``require_manager`` — owner+admin), tenant-scoped and
header/path reconciled exactly like the Phase 66 broadcasts router:

    GET  /api/tenants/{tenant_id}/facebook/inbox/contacts
    GET  /api/tenants/{tenant_id}/facebook/inbox/contacts/{contact_id}/messages
    POST /api/tenants/{tenant_id}/facebook/inbox/contacts/{contact_id}/send

The inbox lets an operator watch live Messenger threads (``flow_contacts`` +
``contact_messages``) and *take over* a conversation. Sending a manual reply:

  1. dispatches the text to Meta's Send API with the page's access token,
  2. appends an ``outbound`` row to the transcript, and
  3. pauses the bot for 24 hours — both the durable
     ``flow_contacts.bot_paused_until`` stamp AND the Redis HITL key — so neither
     the NEXUS Flow engine nor the LangGraph orchestrator replies while the human
     is handling the thread (see the webhook gatekeeper in ``webhook.py``).

The 24-hour auto-resume means an operator who forgets to hand back control does
not silence the bot forever; the next inbound message after the window simply
flows to automation again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import settings
from rag.crypto import decrypt_token
from rag.database.engine import get_async_session
from rag.database.models import (
    ContactMessage,
    FlowContact,
    MessengerPageTenant,
    Tenant,
)
from rag.messenger.flow_engine import (
    _send_graph_message,
    log_contact_message,
)
from rag.messenger.hitl import set_bot_paused
from rag.routers.deps import require_manager

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Inbox"])

# Human-handoff pause duration. Matches Meta's 24h standard messaging window so a
# forgotten takeover auto-resumes automation rather than silencing it forever.
HANDOFF_PAUSE_HOURS = 24

# How many contacts / messages a single list call returns. The thread query is
# index-backed (ix_contact_messages_thread), so these caps protect the payload
# size, not the database.
_CONTACTS_LIMIT = 200
_MESSAGES_LIMIT = 500


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MessagePreview(BaseModel):
    content: str
    direction: str
    created_at: datetime


class InboxContact(BaseModel):
    id: uuid.UUID
    page_id: str
    sender_id: str
    tags: list = Field(default_factory=list)
    hot_lead: bool = False
    last_interaction_at: datetime | None = None
    bot_paused_until: datetime | None = None
    bot_paused: bool = False
    last_message: MessagePreview | None = None


class InboxMessage(BaseModel):
    id: uuid.UUID
    direction: str
    content: str
    created_at: datetime


class ContactThread(BaseModel):
    contact: InboxContact
    messages: list[InboxMessage]


class SendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class SendResponse(BaseModel):
    sent: bool
    bot_paused_until: datetime


# ---------------------------------------------------------------------------
# Guards / helpers
# ---------------------------------------------------------------------------


def _check_path_matches_header(tenant: Tenant, tenant_id: uuid.UUID) -> None:
    """Reject requests whose path id disagrees with ``X-Tenant-ID``."""
    if tenant.id != tenant_id:
        raise HTTPException(
            status_code=400,
            detail="path tenant_id does not match X-Tenant-ID header",
        )


def _pause_active(bot_paused_until: datetime | None, now: datetime) -> bool:
    if bot_paused_until is None:
        return False
    if bot_paused_until.tzinfo is None:
        bot_paused_until = bot_paused_until.replace(tzinfo=timezone.utc)
    return bot_paused_until > now


async def _load_contact_or_404(
    db: AsyncSession, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> FlowContact:
    contact = (
        await db.execute(
            select(FlowContact).where(
                FlowContact.id == contact_id,
                FlowContact.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="contact_not_found")
    return contact


async def _resolve_page_token(db: AsyncSession, page_id: str) -> str:
    """Resolve + decrypt the page access token, or 400 if the page is unusable.

    Mirrors ``flow_engine.run_broadcast_job``'s token resolution: the page→tenant
    mapping holds the encrypted long-lived page token.
    """
    mapping = (
        await db.execute(
            select(MessengerPageTenant).where(
                MessengerPageTenant.facebook_page_id == page_id
            )
        )
    ).scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=400, detail="page_not_connected")
    token = (
        decrypt_token(mapping.page_access_token_enc)
        if mapping.page_access_token_enc
        else None
    )
    if not token:
        raise HTTPException(status_code=400, detail="page_access_token_missing")
    return token


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/facebook/inbox/contacts")
async def list_contacts(
    tenant_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> list[InboxContact]:
    """List the tenant's Messenger contacts, most-recently-active first.

    Two queries (no N+1): the contact rows, then the latest transcript message
    per thread via ``DISTINCT ON (page_id, sender_id)``.
    """
    _check_path_matches_header(tenant, tenant_id)
    now = datetime.now(timezone.utc)

    contacts = (
        (
            await db.execute(
                select(FlowContact)
                .where(FlowContact.tenant_id == tenant.id)
                .order_by(FlowContact.last_interaction_at.desc().nullslast())
                .limit(_CONTACTS_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    # Latest message per (page_id, sender_id) for this tenant in one pass.
    latest_rows = (
        (
            await db.execute(
                select(ContactMessage)
                .where(ContactMessage.tenant_id == tenant.id)
                .distinct(ContactMessage.page_id, ContactMessage.sender_id)
                .order_by(
                    ContactMessage.page_id,
                    ContactMessage.sender_id,
                    ContactMessage.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    previews = {
        (m.page_id, m.sender_id): MessagePreview(
            content=m.content, direction=m.direction, created_at=m.created_at
        )
        for m in latest_rows
    }

    return [
        InboxContact(
            id=c.id,
            page_id=c.page_id,
            sender_id=c.sender_id,
            tags=list(c.tags or []),
            hot_lead=bool(c.hot_lead),
            last_interaction_at=c.last_interaction_at,
            bot_paused_until=c.bot_paused_until,
            bot_paused=_pause_active(c.bot_paused_until, now),
            last_message=previews.get((c.page_id, c.sender_id)),
        )
        for c in contacts
    ]


@router.get("/{tenant_id}/facebook/inbox/contacts/{contact_id}/messages")
async def get_thread(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> ContactThread:
    """Full chat history for one contact, oldest message first."""
    _check_path_matches_header(tenant, tenant_id)
    contact = await _load_contact_or_404(db, tenant.id, contact_id)
    now = datetime.now(timezone.utc)

    rows = (
        (
            await db.execute(
                select(ContactMessage)
                .where(
                    ContactMessage.tenant_id == tenant.id,
                    ContactMessage.page_id == contact.page_id,
                    ContactMessage.sender_id == contact.sender_id,
                )
                .order_by(ContactMessage.created_at.asc())
                .limit(_MESSAGES_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    return ContactThread(
        contact=InboxContact(
            id=contact.id,
            page_id=contact.page_id,
            sender_id=contact.sender_id,
            tags=list(contact.tags or []),
            hot_lead=bool(contact.hot_lead),
            last_interaction_at=contact.last_interaction_at,
            bot_paused_until=contact.bot_paused_until,
            bot_paused=_pause_active(contact.bot_paused_until, now),
        ),
        messages=[
            InboxMessage(
                id=m.id,
                direction=m.direction,
                content=m.content,
                created_at=m.created_at,
            )
            for m in rows
        ],
    )


@router.post("/{tenant_id}/facebook/inbox/contacts/{contact_id}/send")
async def send_manual_reply(
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: SendRequest,
    tenant: Tenant = Depends(require_manager),
    db: AsyncSession = Depends(get_async_session),
) -> SendResponse:
    """Send a human operator's reply and hand the thread off from the bot.

    Dispatches via the Graph API, logs the outbound transcript row, then pauses
    the bot for 24h (durable DB stamp + Redis HITL key) so automation stays quiet
    while the human is on the thread.
    """
    _check_path_matches_header(tenant, tenant_id)
    contact = await _load_contact_or_404(db, tenant.id, contact_id)
    token = await _resolve_page_token(db, contact.page_id)

    text = body.content.strip()
    if not text:
        raise HTTPException(status_code=422, detail="content_empty")

    async with httpx.AsyncClient(
        timeout=settings.outbound_send_timeout_seconds
    ) as client:
        # run=None: this is a human send, not a flow send, so we log the outbound
        # row explicitly below rather than via the flow auto-log path.
        success, status, error = await _send_graph_message(
            client, sender_id=contact.sender_id, text=text, token=token
        )

    if not success:
        _log.warning(
            "inbox.send_failed tenant=%s contact=%s status=%s err=%s",
            tenant.id,
            contact_id,
            status,
            error,
        )
        raise HTTPException(status_code=502, detail=error or "graph_send_failed")

    await log_contact_message(
        tenant_id=tenant.id,
        page_id=contact.page_id,
        sender_id=contact.sender_id,
        direction="outbound",
        content=text,
    )

    # Hand off: pause the bot for 24h via BOTH gates the webhook checks.
    paused_until = datetime.now(timezone.utc) + timedelta(hours=HANDOFF_PAUSE_HOURS)
    contact.bot_paused_until = paused_until
    await db.commit()
    await set_bot_paused(contact.sender_id, duration_s=HANDOFF_PAUSE_HOURS * 3600)

    _log.info(
        "inbox.manual_reply tenant=%s contact=%s page=%s paused_until=%s",
        tenant.id,
        contact_id,
        contact.page_id,
        paused_until.isoformat(),
    )

    return SendResponse(sent=True, bot_paused_until=paused_until)
