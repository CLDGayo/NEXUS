"""Phase 57 — Facebook Comment-to-Message (Private Reply) engine.

Keyword-triggered private replies for Facebook Page comments.

Architecture:
    * ``enqueue_private_reply_job`` — called from the inbound webhook
      (via ``_scheduler``) to park the job on the Redis queue and return
      within Meta's 20 s budget.
    * ``run_private_reply_job`` — called by the worker for each dequeued
      item.  Opens its own DB session (worker holds only an httpx client).

Decision tree inside the job (in order):

1. Resolve tenant + page token.  Unmapped page → drop (non-retryable).
2. Insert ``ProcessedFbComment`` (idempotency lock).  IntegrityError on
   the comment_id PK → duplicate webhook; drop silently.
3. Query ``FacebookAutomation`` rows for the page.  Pick the first whose
   keyword matches.
4a. Match → POST ``/{comment_id}/private_replies`` to the Graph API.
    Any error (4xx, transport) → dead-letter immediately (retryable=False).
4b. No match → LLM-triage fallback via the existing
    ``_handle_comment_triage`` path, passing the per-page token.
    Fail-silent; commit the lock row and return delivered=True.

Idempotency rule: the lock row is committed once the outcome is decided.
Because no send error ever requeues, attempt-vs-retry ambiguity cannot
arise.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rag.config import settings
from rag.crypto import decrypt_token
from rag.database.engine import get_sessionmaker
from rag.database.models import (
    FacebookAutomation,
    MessengerPageTenant,
    ProcessedFbComment,
)
from rag.messenger.queue import QueuedItem, get_queue
from rag.messenger_overlay import current_page_access_token

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_version}"


def _keyword_matches(message: str, keyword: str, match_type: str) -> bool:
    """Return True if *message* matches *keyword* per *match_type*.

    ``exact``    — case-insensitive, whitespace-trimmed equality.
    ``contains`` — case-insensitive substring test.
    """
    msg_norm = message.strip().lower()
    kw_norm = keyword.strip().lower()
    if match_type == "exact":
        return msg_norm == kw_norm
    if match_type == "contains":
        return kw_norm in msg_norm
    # Unknown match type → no match (fail-safe).
    _log.warning("private_reply.unknown_match_type match_type=%s", match_type)
    return False


# ---------------------------------------------------------------------------
# Webhook side — enqueue
# ---------------------------------------------------------------------------


async def enqueue_private_reply_job(
    *,
    page_id: str,
    comment_id: str,
    sender_id: str,
    message: str,
) -> None:
    """Park a private-reply job on the shared Redis queue.

    Returns immediately so the webhook handler stays within Meta's 20 s
    budget.  The worker calls ``run_private_reply_job`` for every dequeued
    item.
    """
    item = QueuedItem(
        correlation_id=f"fb_private_reply:{comment_id}",
        target_url="",  # unused; URL is built at send time
        payload={
            "page_id": page_id,
            "comment_id": comment_id,
            "sender_id": sender_id,
            "message": message,
        },
        target="fb_private_reply",
    )
    await get_queue().enqueue(item)


# ---------------------------------------------------------------------------
# Worker side — job execution
# ---------------------------------------------------------------------------


async def run_private_reply_job(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> tuple[bool, int | None, str | None, bool]:
    """Execute one ``fb_private_reply`` job.

    Returns the worker's ``(delivered, status_code, error, retryable)``
    contract.

    CRITICAL: ``retryable`` is **always** ``False``.  Any Graph-API error
    (code 100, rate-limit 4/17/613, transport, other >=400) dead-letters
    the job immediately.  This means the idempotency lock inserted at step 2
    can never race with its own retry.
    """

    # Imported here to avoid a circular import at module load time.
    from rag.messenger.worker import _classify_graph_error

    page_id = str(payload.get("page_id") or "")
    comment_id = str(payload.get("comment_id") or "")
    message = str(payload.get("message") or "")

    if not page_id or not comment_id:
        _log.warning(
            "private_reply.missing_fields page=%s comment=%s", page_id, comment_id
        )
        return False, None, "missing page_id or comment_id", False

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        # ------------------------------------------------------------------
        # 1. Resolve tenant + token
        # ------------------------------------------------------------------
        row = (
            await db.execute(
                select(MessengerPageTenant).where(
                    MessengerPageTenant.facebook_page_id == page_id
                )
            )
        ).scalar_one_or_none()

        if row is None:
            _log.warning("private_reply.no_mapping page=%s", page_id)
            return True, None, "page unmapped", False  # drop, not DLQ

        tenant_id = row.tenant_id
        token: str | None = (
            decrypt_token(row.page_access_token_enc)
            if row.page_access_token_enc
            else None
        ) or current_page_access_token()

        if not token:
            _log.warning(
                "private_reply.no_token page=%s comment=%s", page_id, comment_id
            )
            # Commit nothing; dead-letter without retry.
            return False, None, "page access token missing", False

        # ------------------------------------------------------------------
        # 2. Idempotency lock — insert ProcessedFbComment, flush.
        #    IntegrityError on the PK → duplicate webhook → drop silently.
        # ------------------------------------------------------------------
        lock_row = ProcessedFbComment(
            comment_id=comment_id,
            page_id=page_id,
            tenant_id=tenant_id,
        )
        db.add(lock_row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            _log.info("private_reply.duplicate_dropped comment=%s", comment_id)
            return True, None, None, False

        # ------------------------------------------------------------------
        # 3. Keyword match
        # ------------------------------------------------------------------
        automations = (
            (
                await db.execute(
                    select(FacebookAutomation).where(
                        FacebookAutomation.page_id == page_id,
                        FacebookAutomation.tenant_id == tenant_id,
                        FacebookAutomation.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

        matched: FacebookAutomation | None = None
        for automation in automations:
            if _keyword_matches(
                message, automation.trigger_keyword, automation.match_type
            ):
                matched = automation
                break

        # ------------------------------------------------------------------
        # 4a. Keyword match → send private reply
        # ------------------------------------------------------------------
        if matched is not None:
            reply_message = (matched.reply_payload or {}).get("message", "")
            url = f"{_graph_base()}/{comment_id}/private_replies"
            try:
                resp = await client.post(
                    url,
                    params={"access_token": token},
                    json={"message": reply_message},
                )
            except httpx.HTTPError as exc:
                error_str = f"transport: {exc.__class__.__name__}: {exc}"
                _log.warning(
                    "private_reply.send_failed comment=%s err=%s",
                    comment_id,
                    error_str,
                )
                # Commit the lock so a retry does not attempt a second send.
                await db.commit()
                return False, None, error_str, False  # dead-letter; no retry

            if resp.status_code < 400:
                await db.commit()
                _log.info(
                    "private_reply.sent comment=%s status=%d keyword=%s",
                    comment_id,
                    resp.status_code,
                    matched.trigger_keyword,
                )
                return True, resp.status_code, None, False

            # Graph error — classify for the log string but force non-retryable.
            try:
                err_body: Any = resp.json()
            except ValueError:
                err_body = None
            _retryable, summary = _classify_graph_error(resp.status_code, err_body)
            _log.warning(
                "private_reply.graph_error comment=%s status=%d err=%s",
                comment_id,
                resp.status_code,
                summary,
            )
            # Commit the lock row, then dead-letter (retryable=False always).
            await db.commit()
            return False, resp.status_code, summary, False

        # ------------------------------------------------------------------
        # 4b. No match → LLM-triage fallback
        # ------------------------------------------------------------------
        _log.info(
            "private_reply.no_match_fallback page=%s comment=%s", page_id, comment_id
        )
        try:
            # Import lazily to avoid heavy orchestrator import chain at module load.
            from rag.messenger.routers.webhook import _handle_comment_triage

            post_id = str(payload.get("post_id") or "")
            sender_id = str(payload.get("sender_id") or "")
            await _handle_comment_triage(
                page_id=page_id,
                comment_id=comment_id,
                post_id=post_id,
                comment_text=message,
                sender_id=sender_id,
                token=token,
            )
        except Exception as exc:  # noqa: BLE001 — fallback is best-effort
            _log.warning(
                "private_reply.fallback_failed comment=%s err=%s", comment_id, exc
            )

        await db.commit()
        return True, None, None, False
