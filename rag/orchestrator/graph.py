"""StateGraph wiring + checkpointer factory + public runner.

The graph fans out to the retrieval arms, fuses with RRF, reranks,
generates with the surface-appropriate system prompt
(``system_brix.md`` for Messenger, ``system_internal.md`` for the SPA),
validates, and either responds or abstains. State is persisted via a
checkpointer keyed on ``thread_key`` so multi-turn conversations within
the same thread carry memory.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from rag.config import settings
from rag.orchestrator.nodes import (
    abstain_node,
    accumulate_context_node,
    direct_fanout_node,
    fuse_node,
    generate_node,
    guardrails_node,
    guardrails_router,
    loop_decision,
    next_subquery_node,
    plan_research_node,
    preprocess_vision_node,
    rerank_node,
    respond_node,
    retrieve_dense_node,
    retrieve_graph_node,
    retrieve_sparse_node,
    rewrite_query_node,
    route_decision,
    route_query_node,
)
from rag.orchestrator.state import NexusState

_log = logging.getLogger(__name__)

_graph: Any | None = None
_checkpointer_override: Any | None = None


def set_checkpointer(saver: Any) -> None:
    """Inject an externally-managed checkpointer (e.g. ``AsyncPostgresSaver``
    whose async context the FastAPI lifespan owns). Forces the cached graph
    to rebuild so subsequent ``get_graph()`` calls pick up the new saver.

    Pass ``None`` to revert to the env-driven default (used by tests).
    """

    global _checkpointer_override
    _checkpointer_override = saver
    reset_graph()


def _build_checkpointer() -> Any:
    """Pick a checkpointer. Priority:

    1. ``set_checkpointer(...)`` override — used by ``rag.main`` lifespan to
       hand in an ``AsyncPostgresSaver`` it already called ``setup()`` on.
    2. ``LANGGRAPH_CHECKPOINT=postgres`` — best-effort sync construction
       (kept for back-compat; the lifespan path is preferred because
       ``AsyncPostgresSaver.from_conn_string`` is an async context manager).
    3. ``MemorySaver()`` — default, safe for tests.
    """

    if _checkpointer_override is not None:
        return _checkpointer_override

    backend = settings.langgraph_checkpoint.lower()
    if backend == "postgres":  # pragma: no cover - exercised in deploy
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver.from_conn_string(settings.postgres_dsn)
    return MemorySaver()


def build_graph() -> Any:
    """Compile a fresh StateGraph. Cached by :func:`get_graph` in production."""

    graph = StateGraph(NexusState)

    # Phase 22.1 — rewrite runs BEFORE vision captioning so the 8B coreference
    # resolver only ever sees raw conversational text. Vision then appends its
    # "[Image Analysis: ...]" block to the already-disambiguated query, keeping
    # the retriever's input free of caption-driven attention sinks.
    # Phase 24 — after vision captioning, ``route_query`` classifies the query
    # into direct vs research mode. Research mode goes through
    # ``plan_research → next_subquery → retrieval → fuse → rerank →
    # accumulate_context → (loop or generate)``. Direct mode skips the planner
    # entirely via the ``direct_fanout`` pass-through; the accumulator still
    # runs once so generate reads a uniform ``accumulated_context``.
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("preprocess_vision", preprocess_vision_node)
    graph.add_node("route_query", route_query_node)
    graph.add_node("direct_fanout", direct_fanout_node)
    graph.add_node("plan_research", plan_research_node)
    graph.add_node("next_subquery", next_subquery_node)
    graph.add_node("retrieve_dense", retrieve_dense_node)
    graph.add_node("retrieve_sparse", retrieve_sparse_node)
    graph.add_node("retrieve_graph", retrieve_graph_node)
    graph.add_node("fuse", fuse_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("accumulate_context", accumulate_context_node)
    graph.add_node("generate", generate_node)
    graph.add_node("guardrails", guardrails_node)
    graph.add_node("respond", respond_node)
    graph.add_node("abstain", abstain_node)

    graph.add_edge(START, "rewrite_query")
    graph.add_edge("rewrite_query", "preprocess_vision")
    graph.add_edge("preprocess_vision", "route_query")

    # Route into one of two fan-out preludes. Both preludes fan out to the
    # same three retrieval arms; ``fuse`` is the barrier that waits for all
    # three to complete on whichever pre-arm path actually fired.
    graph.add_conditional_edges(
        "route_query",
        route_decision,
        {"direct_fanout": "direct_fanout", "plan_research": "plan_research"},
    )

    # Direct path fan-out — single pass, no loop.
    graph.add_edge("direct_fanout", "retrieve_dense")
    graph.add_edge("direct_fanout", "retrieve_sparse")
    graph.add_edge("direct_fanout", "retrieve_graph")

    # Research path fan-out — ``plan_research`` populates ``sub_queries``,
    # then ``next_subquery`` pops the first one and the retrieval arms run
    # on that single sub-query. Subsequent iterations re-enter
    # ``next_subquery`` from ``accumulate_context`` below.
    graph.add_edge("plan_research", "next_subquery")
    graph.add_edge("next_subquery", "retrieve_dense")
    graph.add_edge("next_subquery", "retrieve_sparse")
    graph.add_edge("next_subquery", "retrieve_graph")

    # Shared barrier + post-rerank accumulator (both paths converge here).
    graph.add_edge("retrieve_dense", "fuse")
    graph.add_edge("retrieve_sparse", "fuse")
    graph.add_edge("retrieve_graph", "fuse")
    graph.add_edge("fuse", "rerank")
    graph.add_edge("rerank", "accumulate_context")

    # Cycle: loop back into ``next_subquery`` while sub-queries remain and
    # the iteration cap has not been reached, else proceed to generation.
    graph.add_conditional_edges(
        "accumulate_context",
        loop_decision,
        {"next_subquery": "next_subquery", "generate": "generate"},
    )

    graph.add_edge("generate", "guardrails")
    graph.add_conditional_edges(
        "guardrails",
        guardrails_router,
        {"respond": "respond", "abstain": "abstain"},
    )
    graph.add_edge("respond", END)
    graph.add_edge("abstain", END)

    return graph.compile(checkpointer=_build_checkpointer())


def get_graph() -> Any:
    """Process-wide singleton."""

    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def reset_graph() -> None:
    """Test hook — drops the cached graph so settings changes take effect."""

    global _graph
    _graph = None


async def run_graph(
    *,
    query: str,
    thread_key: str,
    correlation_id: str,
    surface: str = "messenger",
    attachments: list[dict] | None = None,
) -> dict[str, Any]:
    """Public entrypoint used by surface adapters (webhook, SPA).

    Phase 21 — checkpoint persistence errors raised by the underlying
    saver after a node returned a valid answer are caught here and
    surfaced on the returned dict as ``_persistence_error``. Surface
    adapters log this at WARNING but still dispatch the answer — the
    user has the right reply; only memory is degraded.
    """

    state: NexusState = {
        "query": query,
        "thread_key": thread_key,
        "correlation_id": correlation_id,
        "surface": surface,  # type: ignore[typeddict-item]
    }
    if attachments:
        state["attachments"] = attachments
    config = {"configurable": {"thread_id": thread_key}}

    graph = get_graph()
    try:
        result = await graph.ainvoke(state, config=config)
        return dict(result)
    except Exception as exc:
        # Best-effort persistence-error classification. The checkpointer
        # writes happen *between* node executions, so an exception from
        # the saver after a successful ``generate``/``respond`` looks
        # like a top-level ainvoke failure with no recoverable answer.
        # We re-raise unless the failure is clearly post-generation,
        # which we detect by the saver's module path in the traceback.
        if _is_checkpoint_error(exc):
            _log.warning(
                "graph.checkpoint.write_failed thread=%s err=%s",
                thread_key,
                exc,
            )
            # Attempt one read of the last-known state so we can still
            # return the most recent answer the graph produced.
            try:
                snapshot = await graph.aget_state(config)
                values = dict(snapshot.values) if snapshot else {}
            except Exception:  # noqa: BLE001
                values = {}
            values["_persistence_error"] = str(exc)
            return values
        raise


def _is_checkpoint_error(exc: BaseException) -> bool:
    """True when the exception originated inside the LangGraph
    checkpointer (Postgres saver, async pool, psycopg)."""

    tb = exc.__traceback__
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "") or ""
        if module.startswith(("langgraph.checkpoint", "psycopg", "asyncpg")):
            return True
        tb = tb.tb_next
    return False
