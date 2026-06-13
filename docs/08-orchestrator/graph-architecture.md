# Graph Architecture

The NEXUS orchestrator is built on LangGraph's `StateGraph`. This document covers the graph structure, NexusState schema, node wiring, and checkpointer setup.

---

## StateGraph Construction

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

builder = StateGraph(NexusState)

# Register nodes
builder.add_node("entry_node", entry_node)
builder.add_node("sentiment_node", sentiment_node)
builder.add_node("route_query_node", route_query_node)
# ... (all nodes registered)

# Wire edges
builder.set_entry_point("entry_node")
builder.add_edge("entry_node", "sentiment_node")
builder.add_edge("sentiment_node", "route_query_node")
builder.add_conditional_edges(
    "route_query_node",
    route_query_router,
    {
        "direct": "retrieval_node",
        "research": "research_plan_node",
        "abandon": END,
    }
)
# ... (all edges wired)

# Compile with checkpointer
checkpointer = PostgresSaver.from_conn_string(settings.DATABASE_URL)
graph = builder.compile(checkpointer=checkpointer)
```

---

## NexusState

Full typed schema. Every field is optional at graph entry — nodes populate them as they run.

```python
from typing import TypedDict, Optional
from rag.retrieval.rerank import ScoredChunk
from rag.guardrails.pipeline import GuardrailResult
from rag.orchestrator.ai_settings import AiSettings

class NexusState(TypedDict, total=False):
    # Identity
    tenant_id: str
    user_id: str
    thread_id: str
    surface: str                          # "web" | "messenger" | "api"
    conversation_id: Optional[str]

    # Input
    message: str
    message_count: int                    # turns in this thread (for intro/core prompt selection)

    # AI settings (loaded at entry)
    ai_settings: AiSettings

    # Routing
    sentiment: Optional[dict]             # {"label": "positive", "score": 0.87}
    route: str                            # "direct" | "research" | "abandon"

    # Research mode
    subqueries: list[str]
    subquery_results: list[list[ScoredChunk]]

    # Retrieval
    retrieved_chunks: list[ScoredChunk]
    reranked_chunks: list[ScoredChunk]

    # Generation context
    system_prompt: str
    product_context: Optional[list[dict]]

    # Output
    response: str
    citations: list[int]
    sources: list[dict]
    follow_ups: list[str]

    # Guardrails
    guardrail_result: Optional[GuardrailResult]

    # HITL
    hitl_triggered: bool
    hitl_reason: Optional[str]
```

---

## Conditional Routing Functions

LangGraph uses routing functions (not nodes) to decide which edge to follow from conditional nodes:

```python
def route_query_router(state: NexusState) -> str:
    return state["route"]  # "direct" | "research" | "abandon"

def guardrails_router(state: NexusState) -> str:
    result = state.get("guardrail_result")
    if result is None or result.passed:
        return "pass"
    if result.should_escalate:
        return "hitl"
    return "abstain"
```

---

## Node Toggle Wiring

Nodes gated by AI settings toggles use a wrapper pattern:

```python
async def sentiment_node(state: NexusState) -> NexusState:
    if not state["ai_settings"].node_toggles.sentiment_node:
        return state  # Skip — return state unchanged
    # ... actual sentiment logic
```

This keeps the graph topology static — disabled nodes are no-ops rather than removed edges. Avoids graph recompilation per tenant.

---

## Graph Invocation

```python
config = {"configurable": {"thread_id": conversation_id}}

# Streaming (web/API)
async for event in graph.astream_events(
    {"message": user_message, "tenant_id": tenant_id, ...},
    config=config,
    version="v2"
):
    yield format_sse_event(event)

# Non-streaming (Messenger)
final_state = await graph.ainvoke(
    {"message": user_message, "surface": "messenger", ...},
    config=config
)
```

---

## Graph File Locations

| File | Purpose |
|---|---|
| `rag/orchestrator/graph.py` | Graph builder, node registration, edge wiring |
| `rag/orchestrator/state.py` | `NexusState` TypedDict definition |
| `rag/orchestrator/nodes/` | Individual node implementations |
| `rag/orchestrator/llm.py` | Groq client factory, model selection |
| `rag/orchestrator/prompts/` | System prompt templates |
| `rag/orchestrator/ai_settings.py` | `AiSettings` Pydantic model |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `KeyError` in node | State field not populated by prior node | Check node ordering and upstream node output |
| Checkpointer connection error | `DATABASE_URL` wrong or Postgres down | Verify connection string; check `pg_isready` |
| All turns treated as first turn | `message_count` not incrementing | Check checkpointer is persisting state between calls |
| Node running despite toggle off | Toggle wrapper not applied | Verify node has the toggle check at function entry |

---

## Related Docs

- [Nodes Reference](nodes-reference.md)
- [State Persistence](state-persistence.md)
- [Retrieval Routing](retrieval-routing.md)
- [Orchestrator README](README.md)
