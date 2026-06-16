"""Phase 55 — Facebook Page metadata sync.

The Meta webhook delivers a *signal* that a Page's name/about/picture changed;
the authoritative new values are fetched from the Graph API here and written to
``app.messenger_page_tenants``. The work is deferred onto the existing Redis
outbound queue (``target="fb_sync"``) so the webhook returns ``200`` inside
Meta's 20 s budget and the retry/backoff/DLQ machinery is reused verbatim.

Resiliency:
    * The DB write locks ONLY the one page row (``with_for_update``) and is
      FK-scoped to a single tenant — no bulk update, no cross-tenant blast.
    * Expired/revoked page tokens (Graph codes 190/100/200/10) flip
      ``token_status`` and notify the owner; the job dead-letters (non-retryable).
    * Rate-limit codes (4/17/613) requeue with backoff via the worker.
    * An unmapped page id is dropped (no fallback tenant) — same rule as the
      inbound webhook.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import settings
from rag.crypto import decrypt_token
from rag.database.engine import get_sessionmaker
from rag.database.models import MessengerPageTenant
from rag.messenger.queue import QueuedItem, get_queue
from rag.messenger_overlay import current_page_access_token

_log = logging.getLogger(__name__)

# Page object fields we react to (Meta delivers these under entry[].changes[]).
PAGE_SYNC_FIELDS: frozenset[str] = frozenset(
    {"name", "about", "description", "picture"}
)
# Fields we fetch authoritatively from the Graph API on any of the above.
_FETCH_FIELDS = "name,about,picture{url}"


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_version}"


# ---------------------------------------------------------------------------
# Webhook side — enqueue (called from the inbound handler via _scheduler)
# ---------------------------------------------------------------------------


async def schedule_page_sync(page_id: str, field: str | None = None) -> None:
    """Enqueue a sync job for ``page_id`` onto the shared Redis queue."""

    item = QueuedItem(
        correlation_id=f"{settings.facebook_sync_correlation_prefix}:{page_id}",
        target_url="",  # unused for fb_sync; URL is built at send time
        payload={"page_id": page_id, "field": field},
        target="fb_sync",
    )
    await get_queue().enqueue(item)


# ---------------------------------------------------------------------------
# Graph API fetch + parse
# ---------------------------------------------------------------------------


def _parse_page_fields(body: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(body.get("name"), str):
        fields["name"] = body["name"]
    if isinstance(body.get("about"), str):
        fields["about"] = body["about"]
    picture = body.get("picture")
    if isinstance(picture, dict):
        url = ((picture.get("data") or {}).get("url")) if picture.get("data") else None
        if isinstance(url, str) and url:
            fields["picture"] = url
    return fields


# ---------------------------------------------------------------------------
# Atomic, single-row updater
# ---------------------------------------------------------------------------


async def apply_page_update(
    db: AsyncSession, page_id: str, fields: dict[str, Any]
) -> bool:
    """Row-locked write of the fetched fields to the one page row.

    Returns ``True`` if a row was updated, ``False`` if the page is unmapped
    (dropped — never routed to a fallback tenant). Does not commit.
    """

    row = (
        await db.execute(
            select(MessengerPageTenant)
            .where(MessengerPageTenant.facebook_page_id == page_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        _log.warning("fb_sync.no_mapping page=%s", page_id)
        return False

    if "name" in fields:
        row.page_name = fields["name"]
    if "about" in fields:
        row.page_about = fields["about"]
    if "picture" in fields:
        row.profile_picture_url = fields["picture"]
    row.last_synced_at = func.now()
    row.sync_status = "ok"
    return True


async def _mark_token_status(db: AsyncSession, page_id: str, status: str) -> None:
    row = (
        await db.execute(
            select(MessengerPageTenant)
            .where(MessengerPageTenant.facebook_page_id == page_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        row.token_status = status
        row.sync_status = "error"


# ---------------------------------------------------------------------------
# Worker side — the fb_sync job (reuses the worker's error classification)
# ---------------------------------------------------------------------------


async def run_page_sync_job(
    client: httpx.AsyncClient, payload: dict[str, Any]
) -> tuple[bool, int | None, str | None, bool]:
    """Execute one fb_sync job. Returns the worker's
    ``(delivered, status_code, error, retryable)`` contract.

    Opens its own DB session (the worker holds only an httpx client). On an
    auth error the token status is persisted and the job is non-retryable; on
    a rate-limit it is retryable; on success the page row is updated.
    """

    # Imported here to avoid a circular import at module load.
    from rag.messenger.worker import _classify_graph_error

    page_id = str(payload.get("page_id") or "")
    if not page_id:
        return False, None, "fb_sync missing page_id", False

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        row = (
            await db.execute(
                select(MessengerPageTenant).where(
                    MessengerPageTenant.facebook_page_id == page_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            _log.warning("fb_sync.no_mapping page=%s", page_id)
            return False, None, "page unmapped", False  # drop (non-retryable)

        token = (
            decrypt_token(row.page_access_token_enc)
            if row.page_access_token_enc
            else None
        ) or current_page_access_token()
        if not token:
            await _mark_token_status(db, page_id, "invalid")
            await db.commit()
            return False, None, "page access token missing", False

        url = f"{_graph_base()}/{page_id}"
        try:
            resp = await client.get(
                url, params={"fields": _FETCH_FIELDS, "access_token": token}
            )
        except httpx.HTTPError as exc:
            return False, None, f"transport: {exc.__class__.__name__}: {exc}", True

        if resp.status_code < 400:
            fields = _parse_page_fields(resp.json())
            await apply_page_update(db, page_id, fields)
            await db.commit()
            _log.info("fb_sync.applied page=%s fields=%s", page_id, sorted(fields))
            return True, resp.status_code, None, False

        try:
            err_body = resp.json()
        except ValueError:
            err_body = None
        retryable, summary = _classify_graph_error(resp.status_code, err_body)
        if not retryable:
            # Auth/permanent error — persist token status so the UI can prompt
            # a reconnect, then notify the owner. (Rate-limit stays retryable.)
            await _mark_token_status(db, page_id, "revoked")
            await db.commit()
            await _notify_token_revoked(page_id, str(row.tenant_id))
        return False, resp.status_code, summary, retryable


async def _notify_token_revoked(page_id: str, tenant_id: str) -> None:
    """Best-effort owner notification that the page token needs reconnecting."""

    webhook_url = settings.n8n_webhook_notify_url
    if not webhook_url:
        return
    payload = {
        "event": "facebook_token_revoked",
        "page_id": page_id,
        "tenant_id": tenant_id,
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        ) as client:
            await client.post(webhook_url, json=payload)
    except httpx.HTTPError as exc:  # noqa: BLE001 - notify is best-effort
        _log.warning("fb_sync.notify_failed page=%s err=%s", page_id, exc)


# ---------------------------------------------------------------------------
# Connect-time field subscription + metadata seed (called from integrations)
# ---------------------------------------------------------------------------


async def subscribe_and_seed(db: AsyncSession, page_id: str, page_token: str) -> None:
    """Register webhook fields for ``page_id`` and seed initial metadata.

    Best-effort: a Graph failure here must not break the page-bind flow, so
    errors are logged and swallowed. Persists the (encrypted) page token onto
    the existing mapping row so the sync worker can read metadata later.
    """

    from rag.crypto import encrypt_token

    fields_csv = "name,about,description,picture,messages,feed"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        ) as client:
            await client.post(
                f"{_graph_base()}/{page_id}/subscribed_apps",
                params={
                    "subscribed_fields": fields_csv,
                    "access_token": page_token,
                },
            )
            seed = await client.get(
                f"{_graph_base()}/{page_id}",
                params={"fields": _FETCH_FIELDS, "access_token": page_token},
            )
    except httpx.HTTPError as exc:  # noqa: BLE001 - connect-time best effort
        _log.warning("fb_sync.subscribe_failed page=%s err=%s", page_id, exc)
        return

    row = (
        await db.execute(
            select(MessengerPageTenant)
            .where(MessengerPageTenant.facebook_page_id == page_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.page_access_token_enc = encrypt_token(page_token)
    row.token_status = "active"
    row.subscribed_fields = {"fields": fields_csv.split(",")}
    if seed.status_code < 400:
        fields = _parse_page_fields(seed.json())
        if "name" in fields:
            row.page_name = fields["name"]
        if "about" in fields:
            row.page_about = fields["about"]
        if "picture" in fields:
            row.profile_picture_url = fields["picture"]
        row.last_synced_at = func.now()
        row.sync_status = "ok"
    await db.commit()
