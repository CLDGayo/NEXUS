"""Phase 37 — Human-in-the-Loop pause + notification for Messenger.

Two Redis keys per thread:

  nexus:hitl:notified:{sender_id}   — SET-NX, TTL 24h. Ensures the n8n
      owner notification fires at most once per 24h session.

  nexus:hitl:paused:{sender_id}     — SET-EX with ``hitl_pause_duration_s``
      TTL. Present = bot is paused for this sender. TTL expiry = auto-resume.

All Redis ops fail-open: if Redis is unavailable the bot keeps replying
(better a bot reply during owner takeover than total silence).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rag.config import settings
from rag.messenger.redis_client import get_redis

_log = logging.getLogger(__name__)

_NOTIFIED_KEY = "nexus:hitl:notified:{sender_id}"
_PAUSED_KEY = "nexus:hitl:paused:{sender_id}"
_NOTIFY_TTL_S = 86_400  # 24h notify-once window


async def is_bot_paused(sender_id: str) -> bool:
    """True when the bot is paused for this sender (human owner active)."""

    if not sender_id:
        return False
    redis = get_redis()
    try:
        return bool(await redis.exists(_PAUSED_KEY.format(sender_id=sender_id)))
    except Exception as exc:  # noqa: BLE001 — fail-open
        _log.warning("hitl.pause_check_failed sender=%s err=%s", sender_id, exc)
        return False


async def set_bot_paused(sender_id: str) -> None:
    """Pause the bot for this sender. TTL = ``settings.hitl_pause_duration_s``."""

    if not sender_id:
        return
    redis = get_redis()
    ttl = settings.hitl_pause_duration_s
    try:
        await redis.set(_PAUSED_KEY.format(sender_id=sender_id), "1", ex=ttl)
        _log.info("hitl.paused sender=%s ttl=%d", sender_id, ttl)
    except Exception as exc:  # noqa: BLE001
        _log.warning("hitl.pause_set_failed sender=%s err=%s", sender_id, exc)


async def clear_bot_paused(sender_id: str) -> None:
    """Explicit pause clear (TTL handles the common case)."""

    if not sender_id:
        return
    redis = get_redis()
    try:
        await redis.delete(_PAUSED_KEY.format(sender_id=sender_id))
    except Exception as exc:  # noqa: BLE001
        _log.warning("hitl.pause_clear_failed sender=%s err=%s", sender_id, exc)


async def notify_owner_if_needed(
    *,
    sender_id: str,
    page_id: str,
    thread_key: str,
    user_query: str,
    bot_answer: str,
) -> bool:
    """Fire the n8n owner-notification webhook at most once per 24h session.

    Returns True if the notification was sent this call, False if it was
    already sent (or the webhook is not configured / any error occurred).
    """

    webhook_url = settings.n8n_webhook_notify_url
    if not webhook_url or not sender_id:
        return False

    redis = get_redis()
    key = _NOTIFIED_KEY.format(sender_id=sender_id)

    try:
        was_set = await redis.set(key, "1", nx=True, ex=_NOTIFY_TTL_S)
    except Exception as exc:  # noqa: BLE001
        _log.warning("hitl.notify_claim_failed sender=%s err=%s", sender_id, exc)
        return False

    if not was_set:
        return False  # already notified this session

    payload: dict[str, Any] = {
        "sender_id": sender_id,
        "page_id": page_id,
        "thread_key": thread_key,
        "user_query": (user_query or "")[:500],
        "bot_answer": (bot_answer or "")[:1000],
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        ) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        _log.info(
            "hitl.owner_notified sender=%s page=%s status=%d",
            sender_id,
            page_id,
            resp.status_code,
        )
        return True
    except httpx.HTTPStatusError as exc:
        _log.warning(
            "hitl.notify_http_error status=%d body=%r",
            exc.response.status_code,
            exc.response.text[:200],
        )
    except httpx.TimeoutException:
        _log.warning("hitl.notify_timeout sender=%s", sender_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning("hitl.notify_failed sender=%s err=%s", sender_id, exc)
    return False


def is_human_echo(event: dict[str, Any], our_app_id: str | None) -> bool:
    """True when an echo event was sent by a human (Page Inbox / Business Suite).

    Requires ``our_app_id`` to be configured — without it we cannot tell
    bot echoes apart from human echoes, so we fall back to the pre-Phase-37
    behaviour (every ``is_echo`` is silently ignored downstream).

    With ``our_app_id`` set:
      - ``message.is_echo`` must be True.
      - ``message.app_id`` must be absent OR differ from ``our_app_id``.
        Echoes from our own bot carry ``app_id == our_app_id``.
    """

    if not our_app_id:
        return False
    message = event.get("message") or {}
    if not message.get("is_echo"):
        return False
    echo_app_id = message.get("app_id")
    if echo_app_id is None:
        return True  # anomaly — Page Inbox / Business Suite has no app_id
    return str(echo_app_id) != str(our_app_id)


def is_read_event(event: dict[str, Any]) -> bool:
    """True when Meta delivers a read-receipt event."""

    return bool(event.get("read"))
