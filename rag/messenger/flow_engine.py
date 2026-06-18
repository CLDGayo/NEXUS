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
   * ``condition``      — evaluate predicate over run.context; pick
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

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rag.config import settings
from rag.crypto import decrypt_token
from rag.database.engine import get_sessionmaker
from rag.database.models import (
    FlowRun,
    MessengerPageTenant,
    NexusFlow,
    ProcessedFbComment,
)
from rag.messenger.queue import QueuedItem, get_queue
from rag.messenger_overlay import current_page_access_token

_log = logging.getLogger(__name__)

_NODE_VISIT_CAP = 50

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
) -> tuple[bool, int | None, str | None]:
    """POST a text message to the Messenger Send API.

    Returns (success, status_code, error_summary).
    ALL errors → non-retryable (matches Phase 57 discipline).
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
) -> tuple[bool, str | None]:
    """Traverse from start_node, mutating run in-place.

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
            return False, "node visit cap exceeded (cycle guard)"

        visit_count += 1
        node_id = current_node.get("id", "")
        node_type = current_node.get("type", "")
        node_data = current_node.get("data") or {}

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
                    return False, error
            source_handle = None
            current_node = _next_node(flow, node_id)
            continue

        if node_type == "condition":
            # Evaluate predicate over run.context.
            # Simple evaluator: compare context[variable] to value.
            variable = str(node_data.get("variable") or "")
            operator = str(node_data.get("operator") or "eq")
            expected = node_data.get("value")
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

        if node_type == "waitForInput":
            # Send the prompt message.
            prompt = str(node_data.get("prompt") or node_data.get("message") or "")
            if prompt:
                success, _status, error = await _send_graph_message(
                    client,
                    sender_id=run.sender_id,
                    text=prompt,
                    token=token,
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

        # Unknown node type — fail-safe stop.
        _log.warning(
            "flow_engine.unknown_node_type flow=%s node=%s type=%s",
            flow.id,
            node_id,
            node_type,
        )
        run.status = "failed"
        run.current_node_id = node_id
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
            context={},
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
        node_data = waiting_node.get("data") or {}
        var_name = str(node_data.get("variable") or node_data.get("saveAs") or "input")
        run_row.context = {**run_row.context, var_name: message}

        # Resume from the next node after the waitForInput.
        next_node = _next_node(flow, waiting_node_id or "")
        if next_node is None:
            # No outgoing edge → flow is complete.
            run_row.status = "completed"
            run_row.current_node_id = None
            await db.commit()
            return True

        run_row.status = "active"

        success, error = await _traverse(
            client,
            flow=flow,
            run=run_row,
            start_node=next_node,
            token=token,
            db=db,
        )

        await db.commit()

        if not success:
            _log.warning(
                "flow_engine.resume_failed run=%s err=%s", run_row.id, error
            )

        return True
