"""LangGraph node implementations for the Nexus v2 cortex.

Each node is an async function returning a dict of partial state updates.
Phase 5 wraps every node in ``@traced`` so each step emits an OTEL span
and the LLM generation emits a Langfuse ``generation`` event stitched to
the same trace.

The ``guardrails_node`` runs the Phase 5 ``GuardrailsPipeline`` (citation
+ exact-match + entropy), and routes blocked answers to the deterministic
fallback while flagging ``requires_human_handover=True``.

Phase 17 adds surface-aware vision intent overlays so image queries on
Messenger get customer-service-style responses while SPA queries get
structured knowledge-base retrieval.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Literal

import httpx
from qdrant_client.models import FieldCondition, Filter, MatchValue

from rag.config import settings
from rag.orchestrator.ai_settings import (
    _node_enabled,
    assemble_system_prompt,
    resolve_model_params,
)
from rag.guardrails.handover import (
    HandoverSignal,
    emit_handover_signal,
    handover_fallback_text,
)
from rag.guardrails.pipeline import default_pipeline
from rag.orchestrator.llm import LLMError, LLMResult, chat_complete
from rag.orchestrator.sales_tools import (
    SALES_TOOLS_SCHEMA,
    SDR_PERSONA_OVERLAY,
    execute_tool_call,
)
from rag.orchestrator.state import NexusState
from rag.observability.decorators import traced
from rag.retrieval.dense import dense_search
from rag.retrieval.graph import graph_search
from rag.retrieval.rerank import rerank
from rag.retrieval.rrf import reciprocal_rank_fusion
from rag.retrieval.sparse import sparse_search
from rag.retrieval.types import ScoredChunk


def _tenant_filter(state: NexusState) -> Filter:
    """Phase 29 — build the strict-tenant Qdrant filter every retrieval
    node uses. The state's ``tenant_id`` is the slug stamped on every
    chunk payload during ingestion.

    Raises if the slug is missing — that would be a graph-entry bug, and
    silently degrading to "all tenants" would re-open the cross-tenant
    leak Phase 29 closes.
    """

    tenant_id = state.get("tenant_id")
    if not tenant_id:
        raise RuntimeError(
            "NexusState['tenant_id'] is empty; the surface adapter must "
            "populate it at graph entry (Phase 29 strict tenancy)."
        )
    return Filter(
        must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
    )


_log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_GUARDRAILS = default_pipeline()

# ---------------------------------------------------------------------------
# Phase 25 — per-intent RRF weight matrices applied in ``fuse_node``.
# Module-level constants so an eval-driven tuning PR can adjust them
# without touching the engine, the router, or any test wiring. Missing
# intent (router outage, parse failure) collapses to ``_UNIFORM_WEIGHTS``
# so degradation is to today's pre-Phase-25 baseline, never worse.
# ---------------------------------------------------------------------------
_FACTUAL_WEIGHTS: dict[str, float] = {
    "sparse": 1.5,
    "dense": 0.5,
    "graph": 1.0,
}
_CONCEPTUAL_WEIGHTS: dict[str, float] = {
    "dense": 1.5,
    "sparse": 0.5,
    "graph": 1.0,
}
_UNIFORM_WEIGHTS: dict[str, float] = {
    "dense": 1.0,
    "sparse": 1.0,
    "graph": 1.0,
}

_WEIGHTS_BY_INTENT: dict[str, dict[str, float]] = {
    "factual": _FACTUAL_WEIGHTS,
    "conceptual": _CONCEPTUAL_WEIGHTS,
    "mixed": _UNIFORM_WEIGHTS,
}

# ---------------------------------------------------------------------------
# Phase 17 — vision intent overlays
# ---------------------------------------------------------------------------

_VISION_INTENT_MESSENGER = (
    "\n\n--- IMAGE QUERY INSTRUCTIONS ---\n"
    "The user has uploaded an image. Assume they are a customer inquiring "
    "about product availability, similarity, or identifying a person/service. "
    "Search the knowledge base for visual and semantic matches. Respond as a "
    "pleasant customer service representative. If a match is found, "
    "enthusiastically confirm it, provide the specific name/title (e.g., "
    "product name or person's name), and suggest related items or "
    "descriptions. Format cleanly for a chat interface."
)

_VISION_INTENT_SPA = (
    "\n\n--- IMAGE QUERY INSTRUCTIONS ---\n"
    "The user has uploaded an image to query their personal knowledge base. "
    "Search for visual and semantic matches. You must reply with a highly "
    "structured response. Include the following sections:\n"
    "**Source Document:** [Where this image/concept originated]\n"
    "**Identified Subject:** [Name of the person, product, or concept]\n"
    "**Context & Description:** [Details surrounding this item in the vault]\n"
    "**Related Topics:**\n"
    "- [Bullet points of adjacent concepts in the vault]"
)


# Phase 33.3 — conversational continuity hint for multi-turn SDR.
# Appended to the Messenger system prompt when the same product was
# already introduced in an earlier assistant turn, so the LLM stops
# re-describing it and the customer-facing reply stays action-oriented.
_CONTINUITY_NOTE = (
    "\n\n[Continuity Note: The products above have already been "
    "presented to the customer in prior turns. Do NOT re-describe "
    "them. Respond directly to the customer's latest question or "
    "intent. Keep your reply short and action-oriented.]"
)


# ---------------------------------------------------------------------------
# Phase 35 — Cognitive Empathy: sentiment classification prompt + overlays
# ---------------------------------------------------------------------------

_SENTIMENT_SYSTEM_PROMPT = (
    "You classify the emotional tone of a customer message into exactly "
    "one category.\n\n"
    "Categories:\n"
    "- frustrated: angry, upset, complaining, demanding a fix, expressing "
    "dissatisfaction, using profanity or ALL CAPS\n"
    "- urgent: time-sensitive, deadline-driven, needs immediate help, "
    "uses words like 'ASAP', 'now', 'emergency', 'hurry'\n"
    "- excited: enthusiastic, positive, eager to buy, using exclamation "
    "marks, expressing delight\n"
    "- neutral: calm, informational, standard inquiry, no strong emotion\n\n"
    "Respond with ONLY the category name (one word). No punctuation, no "
    "explanation. If uncertain, respond 'neutral'."
)

_VALID_SENTIMENTS: frozenset[str] = frozenset(
    {"frustrated", "urgent", "excited", "neutral"}
)

_FRUSTRATED_OVERLAY = (
    "\n\n--- PRIORITY SUPPORT MODE ---\n"
    "The customer appears frustrated or upset. Follow these rules:\n"
    "1. Do NOT use emojis, exclamation marks, or overly cheerful language.\n"
    "2. Acknowledge their frustration briefly and empathetically in your "
    "opening sentence.\n"
    "3. Prioritize resolution: lead with the direct answer or solution.\n"
    "4. Do NOT attempt any upselling, cross-selling, or sales CTAs.\n"
    "5. Do NOT suggest additional products or prompt for a purchase.\n"
    "6. Keep your tone professional, calm, and solution-focused.\n"
    "7. If you cannot resolve the issue, offer to connect them with a "
    "human agent immediately.\n"
)

_URGENT_OVERLAY = (
    "\n\n--- URGENT REQUEST MODE ---\n"
    "The customer's request is time-sensitive. Follow these rules:\n"
    "1. Lead with the most actionable information immediately.\n"
    "2. Skip preamble and pleasantries — be direct and concise.\n"
    "3. If multiple steps are needed, number them clearly.\n"
    "4. If you cannot provide an instant resolution, state the expected "
    "timeline or next step.\n"
)

_EXCITED_OVERLAY = (
    "\n\n--- ENGAGED CUSTOMER MODE ---\n"
    "The customer is enthusiastic and engaged. Follow these rules:\n"
    "1. Match their energy — be warm and enthusiastic in return.\n"
    "2. Proactively suggest next steps (checkout, related products).\n"
    "3. Reinforce their excitement about the product or service.\n"
)

_SENTIMENT_OVERLAYS: dict[str, str] = {
    "frustrated": _FRUSTRATED_OVERLAY,
    "urgent": _URGENT_OVERLAY,
    "excited": _EXCITED_OVERLAY,
}


def _get_sentiment_overlay(sentiment: str | None) -> str:
    """Return the behavioral overlay for the detected sentiment, or empty."""
    return _SENTIMENT_OVERLAYS.get(sentiment or "", "")


# ---------------------------------------------------------------------------
# Phase 36 — Deep Commerce Context: CRM profile formatter
# ---------------------------------------------------------------------------


def _format_customer_profile(profile: dict[str, Any] | None) -> str:
    """Render the GoHighLevel CRM record into a system-prompt block.

    Returns the empty string when the profile is missing / empty so the
    caller can ``+=`` it unconditionally. Only emits keys that are
    present and non-empty — partial CRM records (e.g. ``lifetime_spend``
    unknown for a new lead) shrink gracefully.
    """
    if not profile or not isinstance(profile, dict):
        return ""

    lines: list[str] = []
    name = profile.get("name") or profile.get("full_name")
    if name:
        lines.append(f"- Name: {name}")
    segment = profile.get("segment")
    if segment:
        lines.append(f"- Segment: {segment}")
    lifetime_spend = profile.get("lifetime_spend")
    if lifetime_spend is not None:
        lines.append(f"- Lifetime Spend: {lifetime_spend}")
    last_order = profile.get("last_order_date")
    if last_order:
        lines.append(f"- Last Order: {last_order}")
    order_count = profile.get("order_count")
    if order_count is not None:
        lines.append(f"- Total Orders: {order_count}")
    tags = profile.get("tags")
    if tags and isinstance(tags, (list, tuple)):
        lines.append(f"- Tags: {', '.join(str(t) for t in tags)}")
    notes = profile.get("notes")
    if notes:
        lines.append(f"- CRM Notes: {notes}")

    if not lines:
        return ""

    return (
        "\n\n--- CUSTOMER CRM PROFILE ---\n"
        "The following CRM context is known about this customer. Use it "
        "to personalise tone, prioritise high-LTV customers, reference "
        "past orders when relevant, and avoid asking for information "
        "you already have. Do NOT recite this profile verbatim to the "
        "customer.\n" + "\n".join(lines) + "\n"
    )


def _history_mentions_any_product(
    history: list[dict[str, Any]],
    products: list[Any],
) -> bool:
    """True when any prior assistant turn includes the name of any product
    currently being presented this turn. Gates the [Continuity Note]
    injection so the LLM only sees it when products were actually
    referenced in earlier prose, not on plain greeting / abstain turns.
    """
    if not history or not products:
        return False
    names = [(getattr(p, "name", "") or "").strip().lower() for p in products]
    names = [n for n in names if n]
    if not names:
        return False
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        blob = content.lower()
        if any(name in blob for name in names):
            return True
    return False


def _load_prompt(surface: str) -> str:
    name = "system_brix.md" if surface == "messenger" else "system_internal.md"
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _format_context(chunks: list[ScoredChunk]) -> str:
    if not chunks:
        return "(no retrieved context)"
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        source = chunk.metadata.get("title") or chunk.metadata.get("file") or chunk.id
        body = chunk.text.strip().replace("\n\n", "\n")
        lines.append(f"[{index}] source: {source}\n{body}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Retrieval nodes
# ---------------------------------------------------------------------------


def _retrieval_query(state: NexusState) -> str:
    """Query string the retrieval+rerank arms search on.

    Phase 22.2 — prefers ``search_query`` (set by ``rewrite_query_node``
    and/or ``preprocess_vision_node``) and falls back to the original
    entry ``query`` when neither node ran (first turn, no images).
    """

    return state.get("search_query") or state.get("query", "") or ""


@traced("graph.node.retrieve_dense", kind="retrieval")
async def retrieve_dense_node(state: NexusState) -> dict:
    hits = await dense_search(
        _retrieval_query(state),
        k=settings.retrieval_k_per_arm,
        filters=_tenant_filter(state),
    )
    return {"dense_hits": hits}


@traced("graph.node.retrieve_sparse", kind="retrieval")
async def retrieve_sparse_node(state: NexusState) -> dict:
    hits = await sparse_search(
        _retrieval_query(state),
        k=settings.retrieval_k_per_arm,
        filters=_tenant_filter(state),
    )
    return {"sparse_hits": hits}


@traced("graph.node.retrieve_graph", kind="retrieval")
async def retrieve_graph_node(state: NexusState) -> dict:
    # The graph arm is more expensive on cold queries than dense/sparse
    # because it touches both SQLite and Qdrant. Still safe to fan out
    # in parallel — langgraph awaits all three at the fuse barrier.
    tenant_id = state.get("tenant_id")
    if not tenant_id:
        raise RuntimeError(
            "NexusState['tenant_id'] is empty; the surface adapter must "
            "populate it at graph entry (Phase 29 strict tenancy)."
        )
    hits = await graph_search(
        _retrieval_query(state),
        k=settings.retrieval_k_per_arm,
        tenant_id=tenant_id,
    )
    return {"graph_hits": hits}


@traced("graph.node.fuse", kind="retrieval")
async def fuse_node(state: NexusState) -> dict:
    dense = state.get("dense_hits", [])
    sparse = state.get("sparse_hits", [])
    graph = state.get("graph_hits", [])
    # Phase 25 — dynamic per-arm weights driven by ``query_intent``.
    # Named rankings are required so RRF can bind each weight to its
    # arm. Missing/None intent ⇒ uniform weights (pre-Phase-25 math).
    intent = state.get("query_intent")
    weights = _WEIGHTS_BY_INTENT.get(intent or "", _UNIFORM_WEIGHTS)
    fused = reciprocal_rank_fusion(
        {"dense": dense, "sparse": sparse, "graph": graph},
        weights=weights,
    )
    _log.info(
        "fuse.weighted intent=%s weights=%s candidates=%d",
        intent,
        weights,
        len(fused),
    )
    return {"fused": fused[: settings.retrieval_k_per_arm]}


@traced("graph.node.rerank", kind="retrieval")
async def rerank_node(state: NexusState) -> dict:
    candidates = state.get("fused", [])
    if not candidates:
        return {"reranked": []}
    # Phase 24 — research mode runs the rerank pass once per sub-query, so
    # each pass uses the tighter ``research_subquery_top_k`` budget to keep
    # the union prompt size bounded after up to ``research_max_iterations``
    # iterations. Direct mode retains the original ``retrieval_top_k``.
    top_k = (
        settings.research_subquery_top_k
        if state.get("is_research_mode")
        else settings.retrieval_top_k
    )
    reranked = await rerank(_retrieval_query(state), candidates, top_k=top_k)
    return {"reranked": reranked}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _collect_image_attachments(state: NexusState) -> list[dict]:
    """Return only valid image attachments, capped at ``vision_max_attachments``."""

    raw = state.get("attachments") or []
    images: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image":
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        images.append({"type": "image", "url": url})
    if len(images) > settings.vision_max_attachments:
        _log.info(
            "vision.attachments_truncated count=%d max=%d",
            len(images),
            settings.vision_max_attachments,
        )
        images = images[: settings.vision_max_attachments]
    return images


@traced("graph.node.preprocess_vision", kind="llm")
async def preprocess_vision_node(state: NexusState) -> dict:
    """Caption incoming image attachments into the text query for retrieval.

    History-aware coreference resolution lives in
    :func:`rewrite_query_node` (Phase 22) — this node now does ONE thing:
    if images are attached, synthesize a short text caption and append it
    to the user's query so the downstream retrievers have something to
    search on.
    """

    images = _collect_image_attachments(state)
    if not images:
        return {}

    # Phase 22.2 — append the caption onto ``search_query`` (the retrieval
    # channel), not ``query``. ``query`` stays the user's natural text so
    # the generation LLM still hears the human; the vision model already
    # receives the raw image on the user turn in ``generate_node``.
    base = state.get("search_query") or state.get("query", "") or ""
    messages = [
        {
            "role": "system",
            "content": (
                "Briefly describe this image to generate a search query for a "
                "knowledge base. Focus on identifiable people, products, text, "
                "and unique objects. Be concise."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": img["url"]}}
                for img in images
            ],
        },
    ]

    try:
        result: LLMResult = await chat_complete(
            messages,
            model=settings.vision_model,
            temperature=0.0,
            max_tokens=100,
        )
    except LLMError as exc:
        _log.warning("preprocess_vision failed: %s", exc)
        return {}

    caption = result.content.strip()
    new_search = f"{base}\n[Image Analysis: {caption}]".strip()
    return {"search_query": new_search}


_AFFIRMATION_REWRITE_SYSTEM_PROMPT = (
    "You rewrite a user's latest message into a standalone search query for a "
    "vector knowledge base.\n\n"
    "Rules:\n"
    "- If the latest message is an affirmation, agreement, or short "
    'continuation ("yes", "yes please", "ok", "sure", "go on", '
    '"tell me more", "and then?", "please do", etc.), YOU MUST replace '
    "it with the subject the assistant just offered or asked about, phrased "
    "as a direct question or noun phrase. Do not return the affirmation "
    "as-is.\n"
    '- If the latest message contains pronouns ("it", "that", "they", '
    '"this", "those", "them") whose antecedents are in the history, '
    "resolve them to the concrete noun.\n"
    "- If the latest message is already self-contained and unambiguous, "
    "return it exactly as-is.\n"
    "- Output ONLY the rewritten query. No commentary, no quotes, no labels, "
    "no leading 'Rewritten:' prefix."
)


@traced("graph.node.rewrite_query", kind="llm")
async def rewrite_query_node(state: NexusState) -> dict:
    """Resolve coreferences in the user's latest query using prior history.

    Skips the LLM call entirely when there is no history (first turn cannot
    have coreferences). On any LLM failure, passes the original query
    through unchanged so retrieval is never blocked by a rewrite error.
    """

    history = state.get("history") or []
    if not history:
        return {}

    current_query = state.get("query", "") or ""
    if not current_query.strip():
        return {}

    history_lines: list[str] = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).capitalize()
        content = str(msg.get("content", ""))
        if role and content:
            history_lines.append(f"{role}: {content}")
    history_str = "\n".join(history_lines)

    user_content = (
        f"Conversation history (oldest first):\n{history_str}\n\n"
        f"Latest user message:\n{current_query}"
    )
    messages = [
        {"role": "system", "content": _AFFIRMATION_REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        result = await chat_complete(
            messages,
            model=settings.followup_model,
            temperature=0.0,
            max_tokens=128,
        )
    except LLMError as exc:
        _log.warning(
            "rewrite_query.failed query=%r history_len=%d error=%s",
            current_query,
            len(history),
            exc,
        )
        return {}

    rewritten = result.content.strip()
    if not rewritten:
        return {}

    _log.info(
        "rewrite_query raw=%r rewritten=%r history_len=%d",
        current_query,
        rewritten,
        len(history),
    )
    # Phase 22.2 — write to ``search_query`` so retrieval gets the
    # disambiguated string while ``query`` stays untouched for the LLM
    # prompt. Prevents "Robotic Repetition" where the model echoed the
    # rewritten search string back to the user as third-person prose.
    return {"search_query": rewritten}


@traced("graph.node.sentiment_analysis", kind="llm")
async def sentiment_analysis_node(state: NexusState) -> dict:
    """Classify the user's emotional tone for downstream prompt tuning.

    Uses the same fast 8B model as ``rewrite_query_node``. On any
    failure (LLM error, unparseable response), defaults to ``neutral``
    so the graph never crashes and the generation path is never blocked.

    Phase 47 — toggleable. Disabled → explicit neutral so downstream
    sentiment-gated branches (e.g. frustrated-SDR interlock) still
    behave predictably.
    """
    # Phase 47 — node toggle.
    if not _node_enabled(state, "sentiment_analysis"):
        return {"sentiment": "neutral"}

    query = (state.get("query") or "").strip()
    if not query:
        return {"sentiment": "neutral"}

    messages = [
        {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    try:
        result = await chat_complete(
            messages,
            model=settings.followup_model,
            temperature=0.0,
            max_tokens=8,
        )
    except LLMError as exc:
        _log.warning("sentiment_analysis.failed defaulting to neutral: %s", exc)
        return {"sentiment": "neutral"}

    raw = result.content.strip().lower().rstrip(".")
    sentiment = raw if raw in _VALID_SENTIMENTS else "neutral"

    _log.info(
        "sentiment_analysis.classified sentiment=%s raw=%r query=%r",
        sentiment,
        result.content,
        query[:120],
    )
    return {"sentiment": sentiment}


@traced("graph.node.enrich_customer_profile", kind="enrichment")
async def enrich_customer_profile_node(state: NexusState) -> dict:
    """Fetch the customer's CRM profile from GoHighLevel via n8n.

    POSTs ``{ "sender_id": ... }`` to ``settings.n8n_webhook_profile_url``
    and writes the returned JSON dict to ``state["customer_profile"]``.
    Silently returns an empty update (no profile) when the webhook URL
    is not configured, the sender_id is empty, or any HTTP / parse /
    network error occurs — the graph must never crash on enrichment
    failure. Downstream nodes treat absence as "no CRM context".
    """

    webhook_url = settings.n8n_webhook_profile_url
    if not webhook_url:
        return {"customer_profile": None}

    sender_id = (state.get("sender_id") or "").strip()
    if not sender_id:
        _log.info("enrich_customer_profile.skip reason=empty_sender_id")
        return {"customer_profile": None}

    payload = {"sender_id": sender_id}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        ) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as exc:
        _log.warning(
            "enrich_customer_profile.http_error status=%d body=%r",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {"customer_profile": None}
    except httpx.TimeoutException:
        _log.warning("enrich_customer_profile.timeout sender_id=%s", sender_id)
        return {"customer_profile": None}
    except Exception as exc:  # noqa: BLE001 — never crash the graph
        _log.warning("enrich_customer_profile.failed err=%s", exc)
        return {"customer_profile": None}

    if not isinstance(body, dict):
        _log.warning("enrich_customer_profile.bad_shape type=%s", type(body).__name__)
        return {"customer_profile": None}

    _log.info(
        "enrich_customer_profile.ok sender_id=%s keys=%s",
        sender_id,
        sorted(body.keys()),
    )
    return {"customer_profile": body}


_HISTORY_INJECT_MAX_TURNS = 10


def _history_messages_for_llm(state: NexusState) -> list[dict[str, Any]]:
    """Strip timestamps from persisted history and cap to the last N turns.

    The LLM doesn't need to see timestamps; they live on disk only so the
    reducer can enforce TTL. Limiting to ``_HISTORY_INJECT_MAX_TURNS``
    keeps prompt-token cost bounded even on long threads.
    """

    history = state.get("history") or []
    if not history:
        return []
    out: list[dict[str, Any]] = []
    for msg in history[-_HISTORY_INJECT_MAX_TURNS:]:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(role, str) and isinstance(content, str):
            out.append({"role": role, "content": content})
    return out


@traced("graph.node.generate", kind="llm")
async def generate_node(state: NexusState) -> dict:
    # Phase 24 — prefer the iteratively-built accumulated_context (populated
    # by the accumulate_context_node on every pass through the loop, in both
    # direct and research modes). Fall back to ``reranked`` so legacy tests
    # and any caller bypassing the loop path still render context.
    accumulated = state.get("accumulated_context") or []
    reranked = state.get("reranked", [])
    chunks_for_prompt = accumulated if accumulated else reranked
    surface = state.get("surface", "messenger")
    prompt = _load_prompt(surface)
    context_block = _format_context(chunks_for_prompt)
    images = _collect_image_attachments(state)
    history_msgs = _history_messages_for_llm(state)
    sentiment = state.get("sentiment")
    customer_profile = state.get("customer_profile")
    crm_block = _format_customer_profile(customer_profile)

    # Phase 33.3 — Messenger continuity gate. Fires when any prior
    # assistant turn already mentioned a product currently in this
    # turn's enriched_products list (populated by
    # ``inject_product_context_node`` for both inject and dedup paths).
    enriched_products: list[Any] = list(state.get("_enriched_products") or [])
    include_continuity = surface == "messenger" and _history_mentions_any_product(
        history_msgs, enriched_products
    )

    # Phase 40 — Proactive Cart Recovery surface. Load the dedicated recovery
    # prompt, inject cart context as a SYSTEM overlay, and bypass SDR tool
    # binding entirely. The checkout URL is supplied in the cart_context dict
    # so no generate_checkout_link tool call is needed or desired here.
    if surface == "outbound_recovery":
        recovery_prompt_path = _PROMPTS_DIR / "system_recovery.md"
        recovery_template = recovery_prompt_path.read_text(encoding="utf-8")
        cart_ctx = state.get("cart_context") or {}
        raw_items: list[Any] = cart_ctx.get("cart_items") or []
        cart_items_block = (
            "\n".join(str(item) for item in raw_items) if raw_items else "(no items)"
        )
        checkout_url = str(cart_ctx.get("checkout_url") or "")
        rendered_recovery = recovery_template.replace(
            "{cart_items_block}", cart_items_block
        ).replace("{checkout_url}", checkout_url)
        # Phase 45 — outbound_recovery: apply core_behavior only (skip
        # situational overlays — this surface owns its own lifecycle prompt).
        _recovery_ai = state.get("ai_settings") or {}
        _recovery_core = (
            (_recovery_ai.get("scenario_prompts") or {}).get("core_behavior") or ""
        ).strip()
        if _recovery_core:
            rendered_recovery = rendered_recovery + "\n" + _recovery_core
        recovery_messages: list[dict[str, Any]] = [
            {"role": "system", "content": rendered_recovery}
        ]
        recovery_messages.extend(history_msgs)
        try:
            recovery_result: LLMResult = await chat_complete(
                recovery_messages,
                model=settings.generation_model,
                temperature=settings.generation_temperature,
                max_tokens=settings.generation_max_tokens,
                extra=None,
            )
        except LLMError as exc:
            _log.warning("generate.recovery_failed; abstaining: %s", exc)
            return {
                "answer": handover_fallback_text(),
                "abstained": True,
                "requires_human_handover": True,
                "handover_reason": f"llm error (recovery): {exc}",
            }
        recovery_content = recovery_result.content.strip()
        if not recovery_content:
            _log.warning(
                "generate.recovery_empty_completion model=%s prompt_tokens=%d",
                recovery_result.model,
                recovery_result.prompt_tokens,
            )
        return {
            "answer": recovery_content,
            "abstained": False,
            "llm_model": recovery_result.model,
            "llm_prompt_tokens": recovery_result.prompt_tokens,
            "llm_completion_tokens": recovery_result.completion_tokens,
            "llm_total_tokens": recovery_result.total_tokens,
            "llm_latency_ms": recovery_result.latency_ms,
        }

    messages: list[dict[str, Any]]
    if images:
        # Multimodal path: instructions+context on system, question+images
        # on user turn. Keeps the citation rules visible while letting the
        # vision model see the actual image content.
        system_content = prompt.replace("{context}", context_block).replace(
            "{question}", "(see user message below)"
        )
        # Phase 17 — inject surface-specific vision intent overlay.
        if surface == "messenger":
            system_content += _VISION_INTENT_MESSENGER
            # Phase 33 — SDR persona (Messenger + vision path).
            # Phase 35 — suppress SDR for frustrated customers.
            # Phase 47 — sdr_persona node toggle.
            if sentiment != "frustrated" and _node_enabled(state, "sdr_persona"):
                system_content += SDR_PERSONA_OVERLAY
            if include_continuity:
                system_content += _CONTINUITY_NOTE
            # Phase 35 — sentiment behavioral overlay.
            overlay = _get_sentiment_overlay(sentiment)
            if overlay:
                system_content += overlay
            # Phase 36 — Deep Commerce Context CRM block.
            if crm_block:
                system_content += crm_block
        else:
            system_content += _VISION_INTENT_SPA
        user_parts: list[dict[str, Any]] = [
            {"type": "text", "text": state["query"]},
        ]
        for img in images:
            user_parts.append({"type": "image_url", "image_url": {"url": img["url"]}})
        messages = [{"role": "system", "content": system_content}]
        # Phase 22 — prior text turns sit between the system contract and
        # the current multimodal user turn so the model has full
        # conversational context without losing image grounding.
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_parts})
        # Phase 48 — vision path keeps the vision model, but still honors the
        # tenant temperature / max_tokens (model_choice is ignored for images).
        _, temperature, max_tokens = resolve_model_params(state.get("ai_settings"))
        model = settings.vision_model
    else:
        # Text-only fallback unchanged from Phase 5 behaviour.
        rendered = prompt.replace("{context}", context_block).replace(
            "{question}", state["query"]
        )
        messages = [{"role": "system", "content": rendered}]
        # Phase 22 — append prior turns AFTER the system prompt. The
        # final user query is already embedded in the system prompt via
        # the ``{question}`` slot, so we do not duplicate it here.
        messages.extend(history_msgs)
        # Phase 48 — resolve per-tenant model / temperature / max_tokens
        # (falls back to settings.* for default tenants).
        model, temperature, max_tokens = resolve_model_params(state.get("ai_settings"))

    # Phase 45 — append lifecycle persona suffix (core_behavior + situational)
    # BEFORE the existing SDR/sentiment/CRM overlay block. Returns an empty
    # string for default tenants, preserving byte-identical behavior.
    _persona_suffix = assemble_system_prompt(
        base=str(messages[0]["content"]),
        ai_settings=state.get("ai_settings") or {},
        state=state,
    )
    if _persona_suffix:
        messages[0]["content"] = str(messages[0]["content"]) + "\n" + _persona_suffix

    # Phase 33 — bind sales tools for Messenger surface only.
    # Phase 33.1 — also gate on ``not images``: the vision model path
    # mixes ``image_url`` content arrays with ``tools`` unreliably across
    # providers, and the multimodal SDR overlay is already appended to
    # ``system_content`` in the ``if images`` branch above.
    extra: dict[str, Any] | None = None
    if surface == "messenger" and not images:
        # Phase 35 — suppress SDR persona AND tool binding for frustrated
        # customers. A frustrated user must never see a checkout CTA.
        # Phase 47 — sdr_persona node toggle.
        if sentiment != "frustrated" and _node_enabled(state, "sdr_persona"):
            extra = {"tools": SALES_TOOLS_SCHEMA, "tool_choice": "auto"}
            messages[0]["content"] = str(messages[0]["content"]) + SDR_PERSONA_OVERLAY
        if include_continuity:
            messages[0]["content"] = str(messages[0]["content"]) + _CONTINUITY_NOTE
        # Phase 35 — sentiment behavioral overlay.
        overlay = _get_sentiment_overlay(sentiment)
        if overlay:
            messages[0]["content"] = str(messages[0]["content"]) + overlay
        # Phase 36 — Deep Commerce Context CRM block.
        if crm_block:
            messages[0]["content"] = str(messages[0]["content"]) + crm_block

    try:
        result: LLMResult = await chat_complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
    except LLMError as exc:
        _log.warning("generation failed; abstaining: %s (vision=%s)", exc, bool(images))
        return {
            "answer": handover_fallback_text(),
            "abstained": True,
            "requires_human_handover": True,
            "handover_reason": f"llm error: {exc}",
        }

    # Phase 33 — tool-call execution loop (Messenger only, max 3 rounds).
    # If the LLM returned tool_calls instead of content, execute them,
    # append the results, and re-call the LLM for the final text answer.
    # Follow-up calls omit ``tools`` to force a text completion and prevent
    # infinite loops.
    _tool_loop_max = 3
    tool_loop = 0
    tenant_id = state.get("tenant_id", "")
    while result.tool_calls and surface == "messenger" and tool_loop < _tool_loop_max:
        tool_loop += 1
        _log.info(
            "generate.tool_loop iteration=%d tool_calls=%d",
            tool_loop,
            len(result.tool_calls),
        )

        messages.append(
            {
                "role": "assistant",
                "content": result.content or None,
                "tool_calls": result.tool_calls,
            }
        )

        for tc in result.tool_calls:
            tool_result = await execute_tool_call(tc, tenant_id=tenant_id)
            messages.append(tool_result)

        try:
            result = await chat_complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMError as exc:
            _log.warning(
                "generation.tool_followup_failed iteration=%d: %s",
                tool_loop,
                exc,
            )
            return {
                "answer": handover_fallback_text(),
                "abstained": True,
                "requires_human_handover": True,
                "handover_reason": f"tool followup llm error: {exc}",
            }

    content = result.content.strip()
    if not content:
        # Phase 25.1 — Groq sometimes returns an empty string when it
        # decides to refuse without emitting the abstention phrase the
        # groundedness validator recognises. Without this WARNING the
        # downstream guardrail block is the only signal anything went
        # wrong, and it's easy to mistake the empty answer for a crash.
        _log.warning(
            "generate.empty_completion model=%s prompt_tokens=%d "
            "completion_tokens=%d latency_ms=%d query=%r",
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.latency_ms,
            (state.get("query") or "")[:200],
        )

    return {
        "answer": content,
        "abstained": False,
        "llm_model": result.model,
        "llm_prompt_tokens": result.prompt_tokens,
        "llm_completion_tokens": result.completion_tokens,
        "llm_total_tokens": result.total_tokens,
        "llm_latency_ms": result.latency_ms,
    }


# ---------------------------------------------------------------------------
# Guardrails + routing
# ---------------------------------------------------------------------------


@traced("graph.node.guardrails", kind="guardrails")
async def guardrails_node(state: NexusState) -> dict:
    answer = state.get("answer", "")
    reranked = state.get("reranked", [])
    query = state.get("query", "") or ""
    # Phase 33.1 — surface-aware threshold for the SDR persona. Messenger
    # tolerates 5 suspicious tokens (vs. 2 on SPA) because the SDR closing
    # CTAs routinely include conversational verbs the validator can't
    # cross-check against the retrieved product chunks.
    # Phase 33.2 — also pass ``has_attachments`` so the pipeline can
    # bypass the citation validator on the vision path (the vision model
    # hallucinates out-of-bounds [n] indices; grounding is the image +
    # product_branch catalog injection, not RAG citation indices).
    surface = state.get("surface", "")
    has_attachments = bool(state.get("attachments"))
    # Phase 33.3 — thread the ``[Product Catalog Match]`` chunk text into
    # the validator's ``query`` (which the ExactMatchValidator forwards
    # to ``_retrieved_text_blob(extra=...)``). Anime / franchise proper
    # nouns inside product names ("King", "Artist", "Special",
    # "Version") then count as grounded and don't trip the suspicious-
    # token ceiling that previously sent legitimate SDR replies to the
    # human-handover fallback.
    catalog_parts: list[str] = []
    for c in reranked:
        if isinstance(c.text, str) and c.text.startswith("[Product Catalog Match]"):
            catalog_parts.append(c.text)
    catalog_text = "\n".join(catalog_parts)
    combined_query = f"{query}\n{catalog_text}" if catalog_text else query

    pipeline_result = _GUARDRAILS.validate(
        answer,
        retrieved=reranked,
        query=combined_query,
        surface=surface,
        has_attachments=has_attachments,
    )

    failed_names = pipeline_result.failed_names

    # Lift the CitationValidator's cited ids into state so downstream
    # surface adapters (Messenger sender, SPA stream) can render source
    # tags without re-parsing the answer.
    cited_ids: tuple[str, ...] = ()
    for r in pipeline_result.results:
        if r.name == "citation":
            cited_ids = tuple(r.metadata.get("cited_ids", []))
            break

    # Phase 47 — hitl_handover node toggle. When disabled, guardrails neither
    # raises a fresh handover flag nor emits the handover signal below; any
    # upstream flag (e.g. a generate-path LLM error) still rides through, and
    # a blocked answer still abstains (guardrails_router keys off
    # ``guardrail_passed``, not ``requires_human_handover``).
    _hitl_enabled = _node_enabled(state, "hitl_handover")

    update: dict = {
        "guardrail_passed": not pipeline_result.blocked,
        "guardrail_reason": _format_pipeline_reason(pipeline_result),
        "uncertainty_score": pipeline_result.uncertainty_score,
        "validator_failures": failed_names,
        "citations": cited_ids,
        "requires_human_handover": (
            pipeline_result.requires_handover
            or bool(state.get("requires_human_handover"))
        )
        if _hitl_enabled
        else bool(state.get("requires_human_handover")),
    }

    if pipeline_result.blocked and _hitl_enabled:
        update["handover_reason"] = update["guardrail_reason"]

        signal = HandoverSignal(
            correlation_id=state.get("correlation_id", ""),
            thread_key=state.get("thread_key", ""),
            surface=state.get("surface", "unknown"),
            reason=update["guardrail_reason"] or "guardrail block",
            validators_failed=failed_names,
            uncertainty_score=pipeline_result.uncertainty_score,
            retrieved_count=len(reranked),
            answer_blocked=True,
        )
        emit_handover_signal(signal)

    return update


def _format_pipeline_reason(pipeline_result) -> str | None:
    failures = pipeline_result.critical_failures
    if not failures:
        return None
    parts = [f"{r.name}: {r.reason or 'failed'}" for r in failures]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Terminal nodes
# ---------------------------------------------------------------------------


@traced("graph.node.respond", kind="terminal")
async def respond_node(state: NexusState) -> dict:
    answer = state.get("answer", "")
    now = time.time()
    return {
        "answer": answer,
        "history": [
            {
                "role": "user",
                "content": state.get("query", ""),
                "timestamp": now,
            },
            {"role": "assistant", "content": answer, "timestamp": now},
        ],
    }


@traced("graph.node.abstain", kind="terminal")
async def abstain_node(state: NexusState) -> dict:
    answer = handover_fallback_text()
    now = time.time()
    return {
        "answer": answer,
        "abstained": True,
        "requires_human_handover": True,
        "handover_reason": state.get("handover_reason")
        or state.get("guardrail_reason")
        or "guardrail abstain",
        "history": [
            {
                "role": "user",
                "content": state.get("query", ""),
                "timestamp": now,
            },
            {"role": "assistant", "content": answer, "timestamp": now},
        ],
    }


# ---------------------------------------------------------------------------
# Conditional router
# ---------------------------------------------------------------------------


def guardrails_router(state: NexusState) -> Literal["respond", "abstain"]:
    if state.get("guardrail_passed"):
        return "respond"
    return "abstain"


# ---------------------------------------------------------------------------
# Phase 24 — Agentic plan-and-solve loop
#
# Two new LLM nodes (router + planner) followed by a state-shuffling loop
# (next_subquery → retrieve/fuse/rerank → accumulate_context) gated by
# ``loop_decision``. Direct-mode queries skip the planner and loop entirely
# via the ``direct_fanout`` pass-through; the accumulator still runs once
# so ``generate_node`` reads a uniform ``accumulated_context`` regardless
# of the path taken.
# ---------------------------------------------------------------------------


_ROUTE_SYSTEM_PROMPT = (
    "You are a query router for a knowledge-base retrieval pipeline.\n\n"
    "Return a JSON object with EXACTLY two keys and no other content:\n"
    '  "is_research_mode": boolean\n'
    '  "intent":           "factual" | "conceptual" | "mixed"\n\n'
    "is_research_mode rules:\n"
    "- true ONLY when the query needs multiple targeted retrieval passes: "
    "explicit comparison between subjects, multi-domain aggregation, "
    "multi-hop reasoning, or time-range summarisation across many notes.\n"
    "- false for single-pass factual lookups, single-entity definitions, "
    "simple recall.\n\n"
    "intent rules:\n"
    "- factual: user seeks specific names, IDs, exact tool names, error "
    "strings, dates, IPs, code symbols, or precise terminology "
    "(favors keyword/sparse retrieval).\n"
    "- conceptual: user seeks summaries, explanations, comparisons, "
    "trade-offs, or broad ideas where paraphrase matters more than "
    "exact tokens (favors dense vector retrieval).\n"
    "- mixed: a combination of both, or ambiguous.\n\n"
    'When uncertain, prefer is_research_mode=false and intent="mixed".\n\n'
    "Respond ONLY with the JSON object, e.g. "
    '{"is_research_mode": false, "intent": "factual"}.'
)


_VALID_INTENTS: frozenset[str] = frozenset({"factual", "conceptual", "mixed"})


def _parse_route_response(text: str) -> tuple[bool, str | None]:
    """Extract ``(is_research_mode, intent)`` from the router's JSON output.

    Tolerates ```` ```json``` ```` code fences and surrounding prose by
    grabbing the first balanced ``{…}`` block. Returns ``(False, None)``
    on any failure so the pipeline degrades to pre-Phase-25 behavior
    (direct mode, uniform fuse weights) instead of blocking.
    """

    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    if not raw.startswith("{"):
        brace = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if brace:
            raw = brace.group(0)

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return False, None

    if not isinstance(parsed, dict):
        return False, None

    is_research = bool(parsed.get("is_research_mode", False))
    intent_raw = parsed.get("intent")
    intent: str | None
    if isinstance(intent_raw, str) and intent_raw.strip().lower() in _VALID_INTENTS:
        intent = intent_raw.strip().lower()
    else:
        intent = None
    return is_research, intent


_PLAN_SYSTEM_PROMPT = (
    "You decompose a complex user query into 2-3 atomic, self-contained "
    "search queries that can each be answered by retrieving from a vector "
    "knowledge base.\n\n"
    "Rules:\n"
    "- Output ONLY a JSON array of strings. No prose. No commentary.\n"
    "- 2 to 3 entries. Never more than 3.\n"
    "- Each entry must be a standalone search phrase that does NOT "
    "depend on other entries for meaning.\n"
    "- Prefer noun phrases over questions.\n\n"
    'Example input: "compare Atlas and Helios across Q1 and Q2"\n'
    'Example output: ["Project Atlas Q1 and Q2 overview", '
    '"Project Helios Q1 and Q2 overview", '
    '"comparison between Atlas and Helios outcomes"]'
)


def _classification_target(state: NexusState) -> str:
    """Text the router classifies against — prefer ``search_query`` (post
    rewrite + caption) so the classifier never makes a decision on raw
    pronoun-laden user text after a coreference rewrite has already run."""

    return state.get("search_query") or state.get("query", "") or ""


@traced("graph.node.route_query", kind="llm")
async def route_query_node(state: NexusState) -> dict:
    """Classify the query into direct/research mode AND intent class.

    Phase 25 — the same cheap 8B call now also returns ``intent`` in
    ``{"factual", "conceptual", "mixed"}`` so ``fuse_node`` can pick the
    right per-arm RRF weight matrix. ``max_tokens=64`` is the smallest
    budget that reliably fits the JSON envelope.

    Any LLM error, JSON parse failure, or unrecognised intent collapses
    to ``(is_research_mode=False, query_intent=None)``. ``fuse_node``
    treats ``None`` as uniform weights, so a router outage degrades to
    pre-Phase-25 behavior — never worse than the prior baseline.
    """

    target = _classification_target(state).strip()
    if not target:
        return {"is_research_mode": False, "query_intent": None}

    messages = [
        {"role": "system", "content": _ROUTE_SYSTEM_PROMPT},
        {"role": "user", "content": target},
    ]

    try:
        result = await chat_complete(
            messages,
            model=settings.followup_model,
            temperature=0.0,
            max_tokens=64,
        )
    except LLMError as exc:
        _log.warning("route_query.failed defaulting to direct: %s", exc)
        return {"is_research_mode": False, "query_intent": None}

    is_research, intent = _parse_route_response(result.content)
    _log.info(
        "route_query.classified mode=%s intent=%s raw=%r",
        "research" if is_research else "direct",
        intent,
        result.content,
    )
    return {"is_research_mode": is_research, "query_intent": intent}


def _parse_plan_response(text: str, fallback: str) -> list[str]:
    """Extract the JSON array of sub-queries from the model output.

    Tolerates ```json``` code fences and surrounding prose. Returns a
    deduped, blank-stripped list of at most 3 strings. Falls back to
    ``[fallback]`` if no usable list can be parsed so the loop still runs
    exactly once instead of getting stuck on no input.
    """

    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    # If the model surrounded the array with prose, grab the first JSON array.
    if not raw.startswith("["):
        bracket = re.search(r"\[.*\]", raw, flags=re.DOTALL)
        if bracket:
            raw = bracket.group(0)

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return [fallback]

    if not isinstance(parsed, list):
        return [fallback]

    out: list[str] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, str):
            continue
        stripped = entry.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(stripped)
        if len(out) >= 3:
            break

    return out or [fallback]


@traced("graph.node.plan_research", kind="llm")
async def plan_research_node(state: NexusState) -> dict:
    """Decompose ``search_query`` into 2-3 atomic sub-queries.

    Only invoked when ``route_query_node`` set ``is_research_mode=True``.
    A planner failure (LLM error, JSON parse) collapses to a single-entry
    loop on the original query — semantically equivalent to direct mode
    but still routes through the loop path so downstream state stays
    consistent.
    """

    target = (state.get("search_query") or state.get("query", "") or "").strip()
    if not target:
        return {"sub_queries": []}

    messages = [
        {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": target},
    ]

    try:
        result = await chat_complete(
            messages,
            model=settings.followup_model,
            temperature=0.2,
            max_tokens=256,
        )
    except LLMError as exc:
        _log.warning("plan_research.failed falling back to single-pass: %s", exc)
        return {"sub_queries": [target]}

    sub_queries = _parse_plan_response(result.content, fallback=target)
    _log.info(
        "plan_research.decomposed count=%d sub_queries=%r",
        len(sub_queries),
        sub_queries,
    )
    return {"sub_queries": sub_queries}


@traced("graph.node.direct_fanout", kind="control")
async def direct_fanout_node(state: NexusState) -> dict:
    """No-op pass-through that gives the router conditional edge a single
    named target before fanning out to the three retrievers. Returning an
    empty update keeps state untouched."""

    return {}


@traced("graph.node.next_subquery", kind="control")
async def next_subquery_node(state: NexusState) -> dict:
    """Pop the next sub-query off the FIFO, write it to ``search_query``
    for this iteration's retrievers, and bump the safety counter that
    ``loop_decision`` checks against ``research_max_iterations``."""

    remaining = list(state.get("sub_queries") or [])
    if not remaining:
        # Defensive: should never happen because ``loop_decision`` exits
        # before re-entering when the queue is empty. Bump the counter so
        # we still trip the hard cap if some future edge change exposes
        # this path.
        return {
            "research_iterations": state.get("research_iterations", 0) + 1,
        }

    head, *rest = remaining
    iterations = state.get("research_iterations", 0) + 1
    return {
        "search_query": head,
        "sub_queries": rest,
        "research_iterations": iterations,
    }


@traced("graph.node.accumulate_context", kind="control")
async def accumulate_context_node(state: NexusState) -> dict:
    """Append this iteration's reranked chunks onto ``accumulated_context``
    via the ``append_chunks`` reducer (dedupes by id, caps the list)."""

    reranked = list(state.get("reranked") or [])
    if not reranked:
        return {}
    return {"accumulated_context": reranked}


def route_decision(state: NexusState) -> Literal["plan_research", "direct_fanout"]:
    """Conditional edge after ``route_query_node``.

    Phase 47 — when ``research_mode`` is disabled the loop never starts;
    control always flows to ``direct_fanout``.
    """
    if not _node_enabled(state, "research_mode"):
        return "direct_fanout"
    return "plan_research" if state.get("is_research_mode") else "direct_fanout"


def loop_decision(state: NexusState) -> Literal["next_subquery", "generate"]:
    """Conditional edge after ``accumulate_context_node``.

    Exits the loop in three cases:
      * direct mode — accumulator ran exactly once, no loop intended.
      * research mode with empty ``sub_queries`` — every planned pass done.
      * research mode at or past the hard iteration cap — defends against
        a planner that emitted more sub-queries than the cap allows.
    """

    if not state.get("is_research_mode"):
        return "generate"
    remaining = state.get("sub_queries") or []
    iterations = state.get("research_iterations", 0)
    if remaining and iterations < settings.research_max_iterations:
        return "next_subquery"
    return "generate"
