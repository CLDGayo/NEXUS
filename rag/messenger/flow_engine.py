"""Phase 58.1 — NEXUS Flow stateful traversal engine.

Architecture mirrors Phase 57 (private_reply.py) discipline verbatim:
    * ``enqueue_flow_job`` — called from the webhook handler; parks the job on
      the Redis queue and returns within Meta's 20 s budget.
    * ``run_flow_job`` — called by the worker for each ``fb_flow`` item.
      Opens its own DB session (worker holds only an httpx client).

Traversal decision tree (run_flow_job):
1. Resolve tenant + page-access token (same path as private_reply.py).
2. Comment idempotency: insert ProcessedFbComment lock; IntegrityError → drop.
3. Load active NexusFlow rows for page_id; match trigger node config against
   the inbound comment/message.
   * No match → **fall back to run_private_reply_job** (Phase 57 coexistence).
4. Start a new FlowRun (or resume a waiting one for DM events).
5. Traverse edges from the trigger node:
   * ``condition``      — evaluate predicate over run.context OR the durable
                          flow_contacts row (Phase 60 contact rules); pick
                          true/false sourceHandle.
   * ``sendMessage``    — POST to Graph API via sender.py.
   * ``waitForInput``   — send prompt, persist current_node_id +
                          status='waiting', return (halted).
   * unknown type       — mark run 'failed', stop.
6. Safety: node-visit cap (50) → cycle guard → DLQ (retryable=False).
   ALL Graph errors → retryable=False (never requeue — same as Phase 57).

``resume_flow_for_dm`` is called from the webhook messaging branch when a
waiting FlowRun exists for the (page_id, sender_id) pair.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from rag.config import settings
from rag.crypto import decrypt_token
from rag.database.engine import get_sessionmaker
from rag.database.models import (
    ContactMessage,
    FlowContact,
    FlowRun,
    MessengerPageTenant,
    NexusFlow,
    ProcessedFbComment,
    Tenant,
)
from rag.i18n import apply_language_directive
from rag.messenger.queue import QueuedItem, get_queue
from rag.messenger_overlay import current_page_access_token

_log = logging.getLogger(__name__)

_NODE_VISIT_CAP = 50

# Regex for template token substitution: {{ token }} or {{ nested.key }}
_TEMPLATE_TOKEN_RE = re.compile(r"{{\s*([\w.]+)\s*}}")

# Phase 60 — condition-node operators that evaluate the durable flow_contacts
# row (written by the updateCrm node) rather than the in-memory run.context.
_CONTACT_RULES = frozenset(
    {"tag_exists", "tag_not_exists", "attribute_equals", "is_hot_lead"}
)

# Phase 64 — Smart Delay. Clamp configured waits to 90 days so a fat-fingered
# value can't park a run effectively forever.
_MAX_DELAY_SECONDS = 90 * 86400


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _delay_seconds(node_data: dict[str, Any]) -> int:
    """Total wait seconds from a smartDelay node's days/hours/minutes (clamped)."""

    def _coerce(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    total = (
        _coerce(node_data.get("days")) * 86400
        + _coerce(node_data.get("hours")) * 3600
        + _coerce(node_data.get("minutes")) * 60
    )
    return min(total, _MAX_DELAY_SECONDS)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_template(text: str, run: FlowRun) -> str:
    """Replace ``{{ token }}`` placeholders with values from run context.

    Exposed tokens:
        * Any key in ``run.context`` (e.g. ``_input``, ``email``, ...).
        * ``sender_id`` / ``page_id`` from the run row.
        * ``_intent`` — stored in context by the aiRouter executor.

    Missing tokens are replaced with an empty string.  Values are coerced to
    ``str`` so numeric/boolean context values render cleanly.
    """
    ctx: dict[str, Any] = {
        **(run.context or {}),
        "sender_id": run.sender_id,
        "page_id": run.page_id,
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        val = ctx.get(key)
        return str(val) if val is not None else ""

    return _TEMPLATE_TOKEN_RE.sub(_replace, text)


async def _get_or_create_contact(
    db: Any,
    tenant_id: Any,
    page_id: str,
    sender_id: str,
) -> FlowContact:
    """Return the FlowContact row for (page_id, sender_id), creating it if absent.

    The caller is responsible for flushing/committing.  JSONB columns are
    initialised to empty list/dict so downstream mutations can rely on them
    being non-None.
    """
    row = (
        await db.execute(
            select(FlowContact).where(
                FlowContact.page_id == page_id,
                FlowContact.sender_id == sender_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = FlowContact(
            tenant_id=tenant_id,
            page_id=page_id,
            sender_id=sender_id,
            tags=[],
            attributes={},
            hot_lead=False,
        )
        db.add(row)

    return row


async def _load_contact(
    db: Any,
    page_id: str,
    sender_id: str,
) -> FlowContact | None:
    """Return the FlowContact row for (page_id, sender_id), or ``None``.

    Read-only counterpart to :func:`_get_or_create_contact`.  Phase 60's
    ``condition`` executor inspects durable CRM state and must NOT create an
    empty contact row as a side effect of merely evaluating a predicate.
    """
    return (
        await db.execute(
            select(FlowContact).where(
                FlowContact.page_id == page_id,
                FlowContact.sender_id == sender_id,
            )
        )
    ).scalar_one_or_none()


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_version}"


def _keyword_matches(message: str, keyword: str, match_type: str) -> bool:
    """Return True if *message* matches *keyword* per *match_type*.

    Reuses the exact logic from private_reply._keyword_matches.
    ``exact``    — case-insensitive, whitespace-trimmed equality.
    ``contains`` — case-insensitive substring test.
    """
    msg_norm = message.strip().lower()
    kw_norm = keyword.strip().lower()
    if match_type == "exact":
        return msg_norm == kw_norm
    if match_type == "contains":
        return kw_norm in msg_norm
    _log.warning("flow_engine.unknown_match_type match_type=%s", match_type)
    return False


def _find_trigger_node(flow: NexusFlow, trigger_type: str) -> dict[str, Any] | None:
    """Return the trigger node dict from flow_state, or None."""
    nodes: list[dict[str, Any]] = (flow.flow_state or {}).get("nodes", [])
    for node in nodes:
        if node.get("type") == trigger_type:
            return node
    return None


def _match_flow_for_comment(
    flows: list[NexusFlow], message: str
) -> NexusFlow | None:
    """Pick the first active flow whose commentTrigger keyword matches."""
    for flow in flows:
        trigger = _find_trigger_node(flow, "commentTrigger")
        if trigger is None:
            continue
        data = trigger.get("data") or {}
        keyword = str(data.get("keyword") or "").strip()
        match_type = str(data.get("matchType") or data.get("match_type") or "exact")
        # keyword="" / "any" means match everything
        if not keyword or keyword.lower() == "any":
            return flow
        if _keyword_matches(message, keyword, match_type):
            return flow
    return None


def _match_flow_for_dm(flows: list[NexusFlow], message: str) -> NexusFlow | None:
    """Pick the first active flow whose dmTrigger keyword matches."""
    for flow in flows:
        trigger = _find_trigger_node(flow, "dmTrigger")
        if trigger is None:
            continue
        data = trigger.get("data") or {}
        keyword = str(data.get("keyword") or "").strip()
        match_type = str(data.get("matchType") or data.get("match_type") or "exact")
        if not keyword or keyword.lower() == "any":
            return flow
        if _keyword_matches(message, keyword, match_type):
            return flow
    return None


def _next_node(
    flow: NexusFlow,
    source_node_id: str,
    source_handle: str | None = None,
) -> dict[str, Any] | None:
    """Follow the first edge from source_node_id (optionally filtered by handle)."""
    edges: list[dict[str, Any]] = (flow.flow_state or {}).get("edges", [])
    nodes_by_id: dict[str, dict[str, Any]] = {
        n["id"]: n for n in (flow.flow_state or {}).get("nodes", [])
    }
    for edge in edges:
        if edge.get("source") != source_node_id:
            continue
        # Handle filter: if source_handle is specified, only match that handle.
        if source_handle is not None and edge.get("sourceHandle") != source_handle:
            continue
        target_id = edge.get("target")
        if target_id and target_id in nodes_by_id:
            return nodes_by_id[target_id]
    return None


async def _send_graph_message(
    client: httpx.AsyncClient,
    *,
    sender_id: str,
    text: str,
    token: str,
    run: FlowRun | None = None,
) -> tuple[bool, int | None, str | None]:
    """POST a text message to the Messenger Send API.

    Returns (success, status_code, error_summary).
    ALL errors → non-retryable (matches Phase 57 discipline).

    Phase 67 — when *run* is supplied, a successful send is best-effort logged
    to ``contact_messages`` as an ``outbound`` row so the Live Chat inbox can
    render the bot/flow side of the conversation. Logging never affects the send
    result (the transcript is observability, not a delivery guarantee).
    """
    from rag.messenger.worker import _classify_graph_error

    url = f"{_graph_base()}/me/messages"
    body = {
        "recipient": {"id": sender_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }
    try:
        resp = await client.post(
            url,
            params={"access_token": token},
            json=body,
        )
    except httpx.HTTPError as exc:
        return False, None, f"transport: {exc.__class__.__name__}: {exc}"

    if resp.status_code < 400:
        if run is not None:
            await log_contact_message(
                tenant_id=run.tenant_id,
                page_id=run.page_id,
                sender_id=sender_id,
                direction="outbound",
                content=text,
            )
        return True, resp.status_code, None

    try:
        err_body: Any = resp.json()
    except ValueError:
        err_body = None
    _retryable, summary = _classify_graph_error(resp.status_code, err_body)
    return False, resp.status_code, summary


async def _traverse(
    client: httpx.AsyncClient,
    *,
    flow: NexusFlow,
    run: FlowRun,
    start_node: dict[str, Any],
    token: str,
    db: Any,
    language: str = "en",
) -> tuple[bool, str | None]:
    """Traverse from start_node, mutating run in-place.

    ``language`` is the tenant's preferred chatbot language (BCP-47 base code);
    Phase 59 injects a "reply exclusively in <language>" directive into the
    system prompt of LLM-based nodes (aiRouter) when it is non-"en".

    Returns (success, error_summary).
    Halts on waitForInput (run.status='waiting') or completion.
    """
    current_node: dict[str, Any] | None = start_node
    visit_count = 0
    source_handle: str | None = None

    while current_node is not None:
        if visit_count >= _NODE_VISIT_CAP:
            _log.warning(
                "flow_engine.cycle_guard flow_id=%s run_id=%s visits=%d",
                flow.id,
                run.id,
                visit_count,
            )
            run.status = "failed"
            run.current_node_id = current_node.get("id")
            run.failed_node_id = current_node.get("id")
            return False, "node visit cap exceeded (cycle guard)"

        visit_count += 1
        node_id = current_node.get("id", "")
        node_type = current_node.get("type", "")
        node_data = current_node.get("data") or {}

        # Phase 58.4a — analytics trail. Reassign (not mutate) so SQLAlchemy
        # flags the JSONB column dirty. Captures every executed node id in order.
        if node_id:
            run.path = [*(run.path or []), node_id]

        _log.debug(
            "flow_engine.traverse flow=%s run=%s node=%s type=%s",
            flow.id,
            run.id,
            node_id,
            node_type,
        )

        if node_type in ("commentTrigger", "dmTrigger"):
            # Trigger node: just advance to the next node.
            source_handle = None
            current_node = _next_node(flow, node_id)
            continue

        if node_type == "sendMessage":
            text = str(node_data.get("message") or node_data.get("text") or "")
            if text:
                success, _status, error = await _send_graph_message(
                    client,
                    sender_id=run.sender_id,
                    text=text,
                    token=token,
                    run=run,
                )
                if not success:
                    _log.warning(
                        "flow_engine.send_failed flow=%s run=%s node=%s err=%s",
                        flow.id,
                        run.id,
                        node_id,
                        error,
                    )
                    run.status = "failed"
                    run.current_node_id = node_id
                    run.failed_node_id = node_id
                    return False, error
            source_handle = None
            current_node = _next_node(flow, node_id)
            continue

        if node_type == "condition":
            # Phase 60 — dual-mode predicate routing to the true/false handle:
            #   * context rules (eq/neq/contains/exists) evaluate run.context.
            #   * contact rules (tag_exists/tag_not_exists/attribute_equals/
            #     is_hot_lead) evaluate the durable flow_contacts row written by
            #     the updateCrm node — real-time, CRM-aware branching.
            variable = str(node_data.get("variable") or "")
            operator = str(node_data.get("operator") or "eq")
            expected = node_data.get("value")

            if operator in _CONTACT_RULES:
                contact = await _load_contact(db, run.page_id, run.sender_id)
                tags = list(contact.tags or []) if contact is not None else []
                attrs = dict(contact.attributes or {}) if contact is not None else {}
                hot_lead = bool(contact.hot_lead) if contact is not None else False
                expected_str = str(expected) if expected is not None else ""

                if operator == "tag_exists":
                    result = expected_str in tags
                elif operator == "tag_not_exists":
                    result = expected_str not in tags
                elif operator == "attribute_equals":
                    result = (
                        variable in attrs and str(attrs.get(variable)) == expected_str
                    )
                else:  # is_hot_lead
                    result = hot_lead
            else:
                actual = run.context.get(variable) if variable else None
                if operator == "eq":
                    result = actual == expected
                elif operator == "neq":
                    result = actual != expected
                elif operator == "contains" and isinstance(actual, str):
                    result = str(expected or "") in actual
                elif operator == "exists":
                    result = variable in run.context
                else:
                    result = bool(actual)

            source_handle = "true" if result else "false"
            current_node = _next_node(flow, node_id, source_handle)
            continue

        if node_type in ("waitForInput", "userInput"):
            # Send the prompt message.
            prompt = str(node_data.get("prompt") or node_data.get("message") or "")
            if prompt:
                success, _status, error = await _send_graph_message(
                    client,
                    sender_id=run.sender_id,
                    text=prompt,
                    token=token,
                    run=run,
                )
                if not success:
                    _log.warning(
                        "flow_engine.wait_prompt_failed flow=%s run=%s err=%s",
                        flow.id,
                        run.id,
                        error,
                    )
                    run.status = "failed"
                    run.current_node_id = node_id
                    run.failed_node_id = node_id
                    return False, error
            # Halt here — resume when DM arrives.
            run.status = "waiting"
            run.current_node_id = node_id
            _log.info(
                "flow_engine.halted_waiting flow=%s run=%s node=%s sender=%s",
                flow.id,
                run.id,
                node_id,
                run.sender_id,
            )
            return True, None

        if node_type == "smartDelay":
            # Phase 64 — pause traversal for a configured duration, then resume
            # via the background poller (resume_due_flows). The continuation is
            # serialized onto the FlowRun row (status='sleeping' + resume_at +
            # current_node_id), so a server restart loses nothing.
            delay_s = _delay_seconds(node_data)
            next_after = _next_node(flow, node_id)
            if next_after is None:
                # Terminal delay — nothing to resume into; complete now.
                run.status = "completed"
                run.current_node_id = None
                return True, None
            if delay_s <= 0:
                # Zero / invalid delay — fall through immediately.
                source_handle = None
                current_node = next_after
                continue
            run.status = "sleeping"
            run.current_node_id = node_id
            run.resume_at = _utcnow() + timedelta(seconds=delay_s)
            _log.info(
                "flow_engine.sleeping flow=%s run=%s node=%s resume_at=%s",
                flow.id,
                run.id,
                node_id,
                run.resume_at.isoformat(),
            )
            return True, None

        if node_type == "aiRouter":
            # Classify the user's message into one of the tenant-defined intents.
            # Mirrors the sentiment_analysis_node pattern: temp=0.0, tiny max_tokens,
            # validate against allowed set, fallback-on-any-error (never raise).
            intents: list[dict[str, Any]] = list(node_data.get("intents") or [])
            labels: list[str] = [str(i.get("id")) for i in intents if i.get("id")]
            input_var = str(node_data.get("inputVariable") or "_input")
            fallback = str(node_data.get("fallbackHandle") or "other")
            user_text = str(run.context.get(input_var) or "")

            picked = fallback
            if labels and user_text:
                try:
                    from rag.orchestrator.llm import chat_complete

                    system_msg = (
                        "Classify the user message into exactly one of these labels: "
                        + ", ".join(labels)
                        + ". Reply with ONLY the label, nothing else."
                    )
                    # Phase 59 — honour the tenant's default chatbot language.
                    # No-op for "en"; downstream LLM text generation inherits it.
                    system_msg = apply_language_directive(system_msg, language)
                    res = await chat_complete(
                        [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_text},
                        ],
                        model=settings.followup_model,
                        temperature=0.0,
                        max_tokens=8,
                    )
                    cand = (res.content or "").strip().lower()
                    labels_lower = [lb.lower() for lb in labels]
                    if cand in labels_lower:
                        # normalise back to the original-cased label id
                        picked = labels[labels_lower.index(cand)]
                    else:
                        picked = fallback
                except Exception as exc:  # noqa: BLE001 — fail-safe, never crash engine
                    _log.warning(
                        "flow_engine.airouter_llm_failed flow=%s node=%s err=%s",
                        flow.id,
                        node_id,
                        exc,
                    )
                    picked = fallback

            _log.debug(
                "flow_engine.airouter_picked flow=%s node=%s picked=%s",
                flow.id,
                node_id,
                picked,
            )
            # Store the picked intent in context so downstream nodes
            # (webhook, updateCrm, condition) can branch on it.
            run.context = {**run.context, "_intent": picked}
            source_handle = picked
            current_node = _next_node(flow, node_id, source_handle)
            continue

        if node_type == "pause":
            # Pause the bot for this sender and optionally send a handoff message.
            # This is a terminal node — the run is marked completed immediately.
            from rag.messenger.hitl import set_bot_paused

            duration_s = int(node_data.get("durationSeconds") or 86400)
            await set_bot_paused(run.sender_id, duration_s=duration_s)
            # Phase 67 — also stamp the durable DB pause so the Live Chat inbox
            # reflects this thread as paused (the Redis key alone is invisible to
            # the inbox query). Best-effort: a stamp failure must not fail the run.
            try:
                await set_contact_bot_paused(
                    page_id=run.page_id,
                    sender_id=run.sender_id,
                    until=datetime.now(timezone.utc) + timedelta(seconds=duration_s),
                )
            except Exception as exc:  # noqa: BLE001 — durable mirror is best-effort
                _log.warning(
                    "flow_engine.pause_db_stamp_failed run=%s err=%s", run.id, exc
                )

            handoff_msg = str(node_data.get("message") or "")
            if handoff_msg:
                success, _status, error = await _send_graph_message(
                    client,
                    sender_id=run.sender_id,
                    text=handoff_msg,
                    token=token,
                    run=run,
                )
                if not success:
                    _log.warning(
                        "flow_engine.pause_msg_failed flow=%s run=%s err=%s",
                        flow.id,
                        run.id,
                        error,
                    )
                    # Non-fatal — pause is already set; proceed to complete.

            run.status = "completed"
            run.current_node_id = None
            _log.info(
                "flow_engine.paused_and_completed flow=%s run=%s sender=%s duration_s=%d",
                flow.id,
                run.id,
                run.sender_id,
                duration_s,
            )
            return True, None

        if node_type == "webhook":
            url = str(node_data.get("url") or "")
            if url:
                rendered = _render_template(
                    str(node_data.get("bodyTemplate") or "{}"), run
                )
                try:
                    payload = json.loads(rendered)
                except json.JSONDecodeError:
                    payload = {"raw": rendered}
                try:
                    resp = await client.post(
                        url,
                        json=payload,
                        timeout=settings.outbound_send_timeout_seconds,
                    )
                    if resp.status_code >= 400:
                        _log.warning(
                            "flow_engine.webhook_non2xx node=%s status=%s",
                            node_id,
                            resp.status_code,
                        )
                except Exception as exc:  # noqa: BLE001 — best-effort, never strand user
                    _log.warning(
                        "flow_engine.webhook_failed node=%s err=%s", node_id, exc
                    )
            source_handle = None
            current_node = _next_node(flow, node_id)
            continue

        if node_type == "updateCrm":
            action = str(node_data.get("action") or "")
            value = node_data.get("value")
            field = str(node_data.get("field") or "")
            contact = await _get_or_create_contact(
                db, run.tenant_id, run.page_id, run.sender_id
            )
            if action == "add_tag" and value:
                # Reassign JSONB — do NOT mutate in place; SQLAlchemy needs a
                # new object to detect the column as dirty.
                contact.tags = sorted(set([*(contact.tags or []), str(value)]))
            elif action == "remove_tag" and value:
                contact.tags = [t for t in (contact.tags or []) if t != str(value)]
            elif action == "set_field" and field:
                contact.attributes = {**(contact.attributes or {}), field: value}
            elif action == "set_hot_lead":
                contact.hot_lead = bool(value) if value is not None else True
            await db.flush()
            source_handle = None
            current_node = _next_node(flow, node_id)
            continue

        # Unknown node type — fail-safe stop.
        _log.warning(
            "flow_engine.unknown_node_type flow=%s node=%s type=%s",
            flow.id,
            node_id,
            node_type,
        )
        run.status = "failed"
        run.current_node_id = node_id
        run.failed_node_id = node_id
        return False, f"unknown node type: {node_type}"

    # End of graph reached normally.
    run.status = "completed"
    run.current_node_id = None
    _log.info(
        "flow_engine.completed flow=%s run=%s sender=%s visits=%d",
        flow.id,
        run.id,
        run.sender_id,
        visit_count,
    )
    return True, None


# ---------------------------------------------------------------------------
# Webhook side — enqueue
# ---------------------------------------------------------------------------


async def enqueue_flow_job(
    *,
    page_id: str,
    comment_id: str,
    sender_id: str,
    message: str,
    post_id: str = "",
) -> None:
    """Park a flow job on the shared Redis queue.

    Returns immediately so the webhook handler stays within Meta's 20 s
    budget.  The worker calls ``run_flow_job`` for every dequeued item.
    """
    item = QueuedItem(
        correlation_id=f"fb_flow:{comment_id}",
        target_url="",  # unused; URL is built at send time
        payload={
            "page_id": page_id,
            "comment_id": comment_id,
            "sender_id": sender_id,
            "message": message,
            "post_id": post_id,
        },
        target="fb_flow",
    )
    await get_queue().enqueue(item)


# ---------------------------------------------------------------------------
# Worker side — job execution
# ---------------------------------------------------------------------------


async def run_flow_job(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> tuple[bool, int | None, str | None, bool]:
    """Execute one ``fb_flow`` job.

    Returns the worker's ``(delivered, status_code, error, retryable)``
    contract.

    CRITICAL: ``retryable`` is **always** ``False``.  Any Graph-API error
    dead-letters the job immediately — identical discipline to Phase 57.
    """
    page_id = str(payload.get("page_id") or "")
    comment_id = str(payload.get("comment_id") or "")
    message = str(payload.get("message") or "")
    sender_id = str(payload.get("sender_id") or "")

    if not page_id or not comment_id:
        _log.warning(
            "flow_engine.missing_fields page=%s comment=%s", page_id, comment_id
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
            _log.warning("flow_engine.no_mapping page=%s", page_id)
            return True, None, "page unmapped", False  # drop, not DLQ

        tenant_id = row.tenant_id
        # Phase 59 — tenant default chatbot language for LLM-node injection.
        tenant_language = (
            await db.scalar(
                select(Tenant.preferred_language).where(Tenant.id == tenant_id)
            )
        ) or "en"
        token: str | None = (
            decrypt_token(row.page_access_token_enc)
            if row.page_access_token_enc
            else None
        ) or current_page_access_token()

        if not token:
            _log.warning(
                "flow_engine.no_token page=%s comment=%s", page_id, comment_id
            )
            return False, None, "page access token missing", False

        # ------------------------------------------------------------------
        # 2. Idempotency lock (reuses processed_fb_comments, same as Phase 57)
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
            _log.info("flow_engine.duplicate_dropped comment=%s", comment_id)
            return True, None, None, False

        # ------------------------------------------------------------------
        # 3. Find matching active flow
        # ------------------------------------------------------------------
        flows = (
            (
                await db.execute(
                    select(NexusFlow).where(
                        NexusFlow.page_id == page_id,
                        NexusFlow.tenant_id == tenant_id,
                        NexusFlow.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

        matched_flow = _match_flow_for_comment(list(flows), message)

        if matched_flow is None:
            # ------------------------------------------------------------------
            # 3b. No flow match → fall back to Phase 57 private reply engine.
            # ------------------------------------------------------------------
            _log.info(
                "flow_engine.no_flow_match_fallback page=%s comment=%s",
                page_id,
                comment_id,
            )
            await db.commit()  # commit the idempotency lock first
            from rag.messenger.private_reply import run_private_reply_job

            # Phase 57 job manages its own DB session; pass original payload.
            # The lock row is already committed so the Phase 57 path will hit
            # IntegrityError on its own flush and drop silently — that is the
            # desired behaviour (the comment is "handled" by the flow engine
            # even when there's no flow match; Phase 57 should not re-process).
            return await run_private_reply_job(client, payload)

        # ------------------------------------------------------------------
        # 4. Start a new FlowRun
        # ------------------------------------------------------------------
        trigger_node = _find_trigger_node(matched_flow, "commentTrigger")
        if trigger_node is None:
            _log.warning(
                "flow_engine.no_trigger_node flow=%s", matched_flow.id
            )
            await db.commit()
            return False, None, "flow has no commentTrigger node", False

        run = FlowRun(
            tenant_id=tenant_id,
            flow_id=matched_flow.id,
            page_id=page_id,
            sender_id=sender_id,
            status="active",
            context={"_input": message},
        )
        db.add(run)
        await db.flush()  # assign run.id

        # ------------------------------------------------------------------
        # 5. Traverse from the trigger node
        # ------------------------------------------------------------------
        success, error = await _traverse(
            client,
            flow=matched_flow,
            run=run,
            start_node=trigger_node,
            token=token,
            db=db,
            language=tenant_language,
        )

        await db.commit()

        if not success:
            _log.warning(
                "flow_engine.traversal_failed flow=%s run=%s err=%s",
                matched_flow.id,
                run.id,
                error,
            )
            return False, None, error, False  # retryable=False always

        return True, None, None, False


async def resume_flow_for_dm(
    client: httpx.AsyncClient,
    *,
    page_id: str,
    sender_id: str,
    message: str,
    token: str,
) -> bool:
    """Resume a waiting FlowRun when an inbound DM arrives.

    Called from the webhook messaging branch after the is_bot_paused() gate.
    Returns True if a waiting run was found and resumed, False otherwise.
    """
    # Phase 67 — defence in depth. The webhook gate already drops paused threads
    # before this is scheduled, but a DB-backed human handoff must halt the flow
    # engine even if that gate is ever bypassed. Returning True ("handled")
    # ensures the caller does NOT fall through to the orchestrator path either.
    if await is_contact_bot_paused(page_id, sender_id):
        _log.info(
            "flow_engine.resume_skipped_paused page=%s sender=%s", page_id, sender_id
        )
        return True

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        run_row = (
            await db.execute(
                select(FlowRun).where(
                    FlowRun.page_id == page_id,
                    FlowRun.sender_id == sender_id,
                    FlowRun.status == "waiting",
                )
            )
        ).scalar_one_or_none()

        if run_row is None:
            return False

        # Load the flow to get the node graph.
        flow = (
            await db.execute(
                select(NexusFlow).where(NexusFlow.id == run_row.flow_id)
            )
        ).scalar_one_or_none()

        if flow is None:
            _log.warning(
                "flow_engine.resume_missing_flow run=%s flow_id=%s",
                run_row.id,
                run_row.flow_id,
            )
            return False

        waiting_node_id = run_row.current_node_id
        nodes_by_id: dict[str, dict[str, Any]] = {
            n["id"]: n for n in (flow.flow_state or {}).get("nodes", [])
        }
        waiting_node = nodes_by_id.get(waiting_node_id or "")

        if waiting_node is None:
            _log.warning(
                "flow_engine.resume_node_not_found run=%s node=%s",
                run_row.id,
                waiting_node_id,
            )
            return False

        # Store the user's reply in context using the variable name from the node.
        # Also update _input so downstream aiRouter nodes always have the latest message.
        node_data = waiting_node.get("data") or {}
        var_name = str(node_data.get("variable") or node_data.get("saveAs") or "input")
        run_row.context = {**run_row.context, var_name: message, "_input": message}

        # Phase 65 — a userInput node also persists the captured reply to the
        # durable flow_contacts custom-fields store (audience CRM), keyed by the
        # node's fieldKey (falling back to the capture variable name).
        if waiting_node.get("type") == "userInput":
            field_key = str(node_data.get("fieldKey") or var_name)
            contact = await _get_or_create_contact(
                db, run_row.tenant_id, run_row.page_id, run_row.sender_id
            )
            contact.attributes = {**(contact.attributes or {}), field_key: message}
            await db.flush()

        # Resume from the next node after the waitForInput.
        next_node = _next_node(flow, waiting_node_id or "")
        if next_node is None:
            # No outgoing edge → flow is complete.
            run_row.status = "completed"
            run_row.current_node_id = None
            await db.commit()
            return True

        run_row.status = "active"

        # Phase 59 — tenant default chatbot language for LLM-node injection.
        tenant_language = (
            await db.scalar(
                select(Tenant.preferred_language).where(Tenant.id == run_row.tenant_id)
            )
        ) or "en"

        success, error = await _traverse(
            client,
            flow=flow,
            run=run_row,
            start_node=next_node,
            token=token,
            db=db,
            language=tenant_language,
        )

        await db.commit()

        if not success:
            _log.warning(
                "flow_engine.resume_failed run=%s err=%s", run_row.id, error
            )

        return True


# ---------------------------------------------------------------------------
# Phase 66 — Audience Broadcasting
# ---------------------------------------------------------------------------


async def touch_contact_interaction(
    *,
    tenant_id: Any,
    page_id: str,
    sender_id: str,
    when: datetime | None = None,
) -> None:
    """Stamp ``flow_contacts.last_interaction_at`` for an inbound Messenger message.

    This timestamp is the anchor for Meta's 24-hour standard messaging window
    enforced by the Broadcasting engine. Call it from the webhook DM branch on
    every inbound *Messenger message* — NOT on comments, because a public
    comment does not open the messaging window under Meta policy.

    Opens its own short transaction: the webhook's request session is
    read-oriented (it backgrounds the heavy work and is not guaranteed to
    commit), so the stamp must not depend on it. Uses a PostgreSQL
    ``INSERT ... ON CONFLICT`` upsert keyed on ``uq_flow_contact`` so concurrent
    inbound turns for the same sender cannot race a select-then-update.

    Best-effort by contract: the caller wraps this in try/except so a DB hiccup
    here can never 5xx the webhook (a 5xx makes Meta retry-storm).
    """
    stamp = when or datetime.now(timezone.utc)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        stmt = (
            pg_insert(FlowContact)
            .values(
                tenant_id=tenant_id,
                page_id=page_id,
                sender_id=sender_id,
                tags=[],
                attributes={},
                hot_lead=False,
                last_interaction_at=stamp,
            )
            .on_conflict_do_update(
                constraint="uq_flow_contact",
                set_={"last_interaction_at": stamp},
            )
        )
        await db.execute(stmt)
        await db.commit()


# ---------------------------------------------------------------------------
# Phase 67 — Live Chat Inbox & Human Handoff
# ---------------------------------------------------------------------------


def _pause_active(bot_paused_until: datetime | None, now: datetime) -> bool:
    """Return True iff a DB-backed bot pause is currently in effect.

    Pure predicate (no I/O) so the gate is trivially unit-testable, mirroring
    ``broadcasts._within_messaging_window``. ``None`` (never paused / cleared) is
    never active; a naive timestamp is defensively treated as UTC.
    """
    if bot_paused_until is None:
        return False
    if bot_paused_until.tzinfo is None:
        bot_paused_until = bot_paused_until.replace(tzinfo=timezone.utc)
    return bot_paused_until > now


async def is_contact_bot_paused(page_id: str, sender_id: str) -> bool:
    """True when a human operator has paused the bot for this thread.

    The durable twin of ``hitl.is_bot_paused`` (Redis): checks
    ``flow_contacts.bot_paused_until`` against ``now``. Fail-open (return False)
    on any DB error so a transient hiccup can never permanently silence the bot
    — the inbox send also sets the Redis pause, which gates independently.
    """
    if not page_id or not sender_id:
        return False
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            paused_until = await db.scalar(
                select(FlowContact.bot_paused_until).where(
                    FlowContact.page_id == page_id,
                    FlowContact.sender_id == sender_id,
                )
            )
        return _pause_active(paused_until, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 — fail-open like the Redis gate
        _log.warning(
            "flow_engine.contact_pause_check_failed sender=%s err=%s",
            sender_id,
            exc,
        )
        return False


async def set_contact_bot_paused(
    *,
    page_id: str,
    sender_id: str,
    until: datetime,
) -> None:
    """Stamp ``flow_contacts.bot_paused_until`` for a thread.

    Upserts on ``uq_flow_contact`` so it is safe even when no contact row exists
    yet (e.g. a flow ``pause`` node fired before any inbound DM). Opens its own
    short transaction — callers wrap it in try/except (best-effort durable
    mirror of the Redis pause).
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        # tenant_id is required on insert; resolve it from the page mapping so a
        # brand-new contact row satisfies the NOT NULL FK. If the page is
        # unmapped we cannot create a row — skip silently (the Redis pause still
        # applies and the inbox only lists mapped pages).
        tenant_id = await db.scalar(
            select(MessengerPageTenant.tenant_id).where(
                MessengerPageTenant.facebook_page_id == page_id
            )
        )
        if tenant_id is None:
            return
        stmt = (
            pg_insert(FlowContact)
            .values(
                tenant_id=tenant_id,
                page_id=page_id,
                sender_id=sender_id,
                tags=[],
                attributes={},
                hot_lead=False,
                bot_paused_until=until,
            )
            .on_conflict_do_update(
                constraint="uq_flow_contact",
                set_={"bot_paused_until": until},
            )
        )
        await db.execute(stmt)
        await db.commit()


async def log_contact_message(
    *,
    tenant_id: Any,
    page_id: str,
    sender_id: str,
    direction: str,
    content: str,
) -> None:
    """Append one row to ``contact_messages`` for the Live Chat inbox transcript.

    Best-effort by contract: every caller (webhook inbound, flow/bot outbound,
    human operator send) wraps or tolerates failure, because the transcript is
    observability — a logging hiccup must never break message delivery or 5xx the
    webhook. Empty ``content`` is dropped (nothing useful to render).
    """
    if not content or not sender_id:
        return
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            db.add(
                ContactMessage(
                    tenant_id=tenant_id,
                    page_id=page_id,
                    sender_id=sender_id,
                    direction=direction,
                    content=content,
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — transcript is best-effort
        _log.warning(
            "flow_engine.contact_message_log_failed sender=%s dir=%s err=%s",
            sender_id,
            direction,
            exc,
        )


async def enqueue_broadcast_job(
    *,
    page_id: str,
    flow_id: str,
    sender_id: str,
    tenant_id: str,
) -> None:
    """Park one broadcast send on the shared Redis queue (one job per recipient).

    The worker calls ``run_broadcast_job`` for every dequeued ``fb_broadcast``
    item. Keeping the fan-out on the queue means the ``/fire`` request returns
    immediately and a large audience can never block the API worker or exceed a
    request budget.
    """
    item = QueuedItem(
        correlation_id=f"fb_broadcast:{flow_id}:{sender_id}",
        target_url="",  # unused; URL is built at send time
        payload={
            "page_id": page_id,
            "flow_id": flow_id,
            "sender_id": sender_id,
            "tenant_id": tenant_id,
        },
        target="fb_broadcast",
    )
    await get_queue().enqueue(item)


def _find_any_trigger_node(flow: NexusFlow) -> dict[str, Any] | None:
    """Return the flow's trigger node (any trigger type), or None.

    A broadcast starts a flow regardless of which inbound surface its trigger
    models: ``_traverse`` skips the trigger node and advances to its successor,
    so the trigger type only matters for matching live inbound events, not for a
    programmatic broadcast send.
    """
    trigger_types = {"commentTrigger", "dmTrigger", "storyTrigger"}
    nodes: list[dict[str, Any]] = (flow.flow_state or {}).get("nodes", [])
    for node in nodes:
        if node.get("type") in trigger_types:
            return node
    return None


async def run_broadcast_job(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> tuple[bool, int | None, str | None, bool]:
    """Execute one ``fb_broadcast`` job: start ``flow_id`` for one ``sender_id``.

    Mirrors ``run_flow_job``'s tenant/token resolution but is driven by an
    explicit ``flow_id`` (the broadcast target) instead of a comment keyword
    match, and carries NO ``processed_fb_comments`` idempotency lock — a
    broadcast is an intentional, operator-initiated send, not a webhook-deduped
    event.

    CRITICAL: ``retryable`` is **always** ``False`` — any Graph-API error
    dead-letters this single recipient's job immediately (Phase 57/58
    discipline) so one bad recipient can never retry-storm the page.
    """
    page_id = str(payload.get("page_id") or "")
    flow_id = str(payload.get("flow_id") or "")
    sender_id = str(payload.get("sender_id") or "")

    if not page_id or not flow_id or not sender_id:
        _log.warning(
            "broadcast.missing_fields page=%s flow=%s sender=%s",
            page_id,
            flow_id,
            sender_id,
        )
        return False, None, "missing page_id, flow_id or sender_id", False

    try:
        flow_uuid = uuid.UUID(flow_id)
    except ValueError:
        _log.warning("broadcast.bad_flow_id flow=%s", flow_id)
        return True, None, "invalid flow_id", False  # drop, not DLQ

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        # 1. Resolve tenant + page token from the page mapping.
        mapping = (
            await db.execute(
                select(MessengerPageTenant).where(
                    MessengerPageTenant.facebook_page_id == page_id
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            _log.warning("broadcast.no_mapping page=%s", page_id)
            return True, None, "page unmapped", False  # drop, not DLQ

        tenant_id = mapping.tenant_id
        token = (
            decrypt_token(mapping.page_access_token_enc)
            if mapping.page_access_token_enc
            else None
        ) or current_page_access_token()
        if not token:
            _log.warning("broadcast.no_token page=%s flow=%s", page_id, flow_id)
            return False, None, "page access token missing", False

        tenant_language = (
            await db.scalar(
                select(Tenant.preferred_language).where(Tenant.id == tenant_id)
            )
        ) or "en"

        # 2. Load the target flow, scoped to the resolved tenant (defence in
        #    depth — the router already authorised, but the worker must never
        #    send a flow that does not belong to the page's tenant).
        flow = (
            await db.execute(
                select(NexusFlow).where(
                    NexusFlow.id == flow_uuid,
                    NexusFlow.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if flow is None:
            _log.warning(
                "broadcast.flow_not_found flow=%s tenant=%s", flow_id, tenant_id
            )
            return True, None, "flow not found for tenant", False  # drop, not DLQ

        trigger_node = _find_any_trigger_node(flow)
        if trigger_node is None:
            _log.warning("broadcast.no_trigger flow=%s", flow_id)
            return False, None, "flow has no trigger node", False

        # 3. Start a fresh FlowRun and traverse from the trigger node.
        run = FlowRun(
            tenant_id=tenant_id,
            flow_id=flow.id,
            page_id=page_id,
            sender_id=sender_id,
            status="active",
            context={"_input": "", "_broadcast": True},
        )
        db.add(run)
        await db.flush()  # assign run.id

        success, error = await _traverse(
            client,
            flow=flow,
            run=run,
            start_node=trigger_node,
            token=token,
            db=db,
            language=tenant_language,
        )
        await db.commit()

        if not success:
            _log.warning(
                "broadcast.traversal_failed flow=%s run=%s err=%s",
                flow.id,
                run.id,
                error,
            )
            return False, None, error, False  # retryable=False always

        return True, None, None, False


# ---------------------------------------------------------------------------
# Phase 64 — Smart Delay: time-based resume poller
# ---------------------------------------------------------------------------


async def _resolve_page_token(db: Any, page_id: str) -> str | None:
    """Page access token for ``page_id`` (decrypted binding → global overlay)."""

    row = (
        await db.execute(
            select(MessengerPageTenant).where(
                MessengerPageTenant.facebook_page_id == page_id
            )
        )
    ).scalar_one_or_none()
    token = (
        decrypt_token(row.page_access_token_enc)
        if row is not None and row.page_access_token_enc
        else None
    )
    return token or current_page_access_token()


async def _resume_one_delayed(
    client: httpx.AsyncClient, run_id: uuid.UUID, cutoff: datetime
) -> bool:
    """Claim and resume a single due sleeping run. Returns True if handled."""

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        # Claim under SKIP LOCKED so concurrent workers never double-resume.
        run = (
            await db.execute(
                select(FlowRun)
                .where(
                    FlowRun.id == run_id,
                    FlowRun.status == "sleeping",
                    FlowRun.resume_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if run is None:
            return False  # already claimed elsewhere or no longer due

        flow = (
            await db.execute(select(NexusFlow).where(NexusFlow.id == run.flow_id))
        ).scalar_one_or_none()
        delay_node_id = run.current_node_id
        next_node = _next_node(flow, delay_node_id or "") if flow is not None else None

        if flow is None or next_node is None:
            # Flow deleted, or the delay node has no outgoing edge — close the
            # run rather than letting it linger as a permanently-sleeping row.
            run.status = "completed"
            run.current_node_id = None
            run.resume_at = None
            await db.commit()
            return True

        token = await _resolve_page_token(db, run.page_id)
        if not token:
            _log.warning(
                "flow_engine.resume_delay_no_token run=%s page=%s",
                run.id,
                run.page_id,
            )
            run.status = "failed"
            run.resume_at = None
            await db.commit()
            return True

        # Phase 59 — resume under the tenant's default chatbot language.
        tenant_language = (
            await db.scalar(
                select(Tenant.preferred_language).where(Tenant.id == run.tenant_id)
            )
        ) or "en"

        run.status = "active"
        run.resume_at = None
        success, error = await _traverse(
            client,
            flow=flow,
            run=run,
            start_node=next_node,
            token=token,
            db=db,
            language=tenant_language,
        )
        await db.commit()
        if not success:
            _log.warning("flow_engine.resume_delay_failed run=%s err=%s", run.id, error)
        return True


async def resume_due_flows(
    client: httpx.AsyncClient,
    *,
    batch: int = 25,
    now: datetime | None = None,
) -> int:
    """Resume every sleeping FlowRun whose ``resume_at`` is due.

    Polled by the outbound worker each loop iteration. DB-backed scheduling:
    the only state is the ``flow_runs`` rows, so an API/worker restart simply
    re-scans overdue runs on boot — nothing is lost. Returns the count resumed.
    """

    cutoff = now or _utcnow()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        due_ids = (
            (
                await db.execute(
                    select(FlowRun.id)
                    .where(
                        FlowRun.status == "sleeping",
                        FlowRun.resume_at <= cutoff,
                    )
                    .order_by(FlowRun.resume_at)
                    .limit(batch)
                )
            )
            .scalars()
            .all()
        )

    resumed = 0
    for run_id in due_ids:
        if await _resume_one_delayed(client, run_id, cutoff):
            resumed += 1
    if resumed:
        _log.info("flow_engine.resume_due_flows resumed=%d", resumed)
    return resumed
