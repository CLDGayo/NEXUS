# Nodes Reference

All nodes in the NEXUS LangGraph orchestrator, their inputs, outputs, toggle gates, and conditions.

---

## Node Catalogue

### `entry_node`

Initializes the turn. Loads tenant AI settings, resolves system prompt, increments message count.

| Input | Output |
|---|---|
| `tenant_id`, `user_id`, `thread_id`, `surface`, `message` | `ai_settings`, `system_prompt`, `message_count` |

**No toggle gate** — always runs.

---

### `sentiment_node`

Classifies user message sentiment and intent using the 8b fast model.

| Input | Output |
|---|---|
| `message` | `sentiment: {"label": str, "score": float, "intent": str}` |

**Toggle gate:** `ai_settings.node_toggles.sentiment_node`

Output is used by `route_query_node` (boost research threshold for confused/frustrated users) and `guardrails_router` (HITL escalation).

---

### `route_query_node`

Classifies the query and sets the routing branch.

| Input | Output |
|---|---|
| `message`, `sentiment` | `route: "direct" \| "research" \| "abandon"` |

**No toggle gate** — always runs.

Routing logic:
- `abandon` — gibberish, empty, or clearly out-of-scope
- `research` — multi-part questions, comparisons, "explain X vs Y", or user appears confused
- `direct` — everything else

→ See [Retrieval Routing](retrieval-routing.md) for full routing decision matrix.

---

### `research_plan_node`

Decomposes a complex query into 2–4 focused subqueries.

| Input | Output |
|---|---|
| `message` | `subqueries: list[str]` |

**Toggle gate:** `ai_settings.node_toggles.research_mode_node`

LLM call with a decomposition prompt. Example:
- Input: "Compare the Pro and Enterprise plans, including pricing, features, and support"
- Output: `["Pro plan pricing", "Enterprise plan pricing", "Pro vs Enterprise features", "Pro vs Enterprise support"]`

---

### `subquery_node`

Runs hybrid retrieval for each subquery in parallel. Results stored per-subquery for the accumulator.

| Input | Output |
|---|---|
| `subqueries` | `subquery_results: list[list[ScoredChunk]]` |

**Toggle gate:** `ai_settings.node_toggles.research_mode_node`

---

### `accumulate_node`

Merges and deduplicates chunks from all subquery results. Preserves per-chunk score metadata.

| Input | Output |
|---|---|
| `subquery_results` | `retrieved_chunks: list[ScoredChunk]` |

**Toggle gate:** `ai_settings.node_toggles.research_mode_node`

---

### `retrieval_node`

Single-pass hybrid retrieval: dense (Qdrant) + sparse (BM25) + graph (Postgres wikilink walk) fused via RRF.

| Input | Output |
|---|---|
| `message`, `tenant_id` | `retrieved_chunks: list[ScoredChunk]` (up to `RETRIEVE_K` per arm) |

**No toggle gate** — always runs (unless route = `abandon`).

→ See [Stage 3 — Hybrid Retrieval](../02-rag-pipeline/stage-3-hybrid-retrieval.md) for arm detail.

---

### `rerank_node`

Cross-encoder reranker trims `retrieved_chunks` to `TOP_K`.

| Input | Output |
|---|---|
| `retrieved_chunks`, `message` | `reranked_chunks: list[ScoredChunk]` |

**No toggle gate** — always runs.

Applies `RERANK_CONFIDENCE_FLOOR` — chunks below threshold are dropped before generation.

---

### `inject_product_context_node`

Fetches matching products from the catalog and injects structured cards into generation context.

| Input | Output |
|---|---|
| `message`, `tenant_id` | `product_context: list[dict]` |

**Toggle gate:** `ai_settings.node_toggles.product_context_node`

Products are matched by embedding similarity against the product catalog. Injected as structured context separate from retrieved vault chunks.

---

### `generate_node`

Primary LLM generation. Calls Groq with assembled system prompt, retrieved chunks, and product context. Streams tokens via SSE.

| Input | Output |
|---|---|
| `reranked_chunks`, `product_context`, `system_prompt`, `message`, `ai_settings.model_params` | `response`, `citations`, `sources` |

**No toggle gate** — always runs.

---

### `guardrails_node`

Runs three validators on the generated response.

| Input | Output |
|---|---|
| `response`, `reranked_chunks`, `message` | `guardrail_result: GuardrailResult` |

**Toggle gate:** `ai_settings.node_toggles.guardrails_node`

Validators: `CitationValidator`, `ExactMatchValidator`, `EntropyValidator`.

→ See [Guardrails Integration](guardrails-integration.md).

---

### `follow_up_node`

Generates 2–3 follow-up question suggestions based on the response and conversation context.

| Input | Output |
|---|---|
| `response`, `message`, `surface` | `follow_ups: list[str]` |

**Toggle gate:** `ai_settings.node_toggles.follow_up_node`

For `surface="messenger"`, follow-ups are formatted as Messenger quick reply buttons (max 20 chars each). For web/API, they are plain strings.

---

### `hitl_node`

Sets the HITL pause key in Redis and sends owner notification.

| Input | Output |
|---|---|
| `tenant_id`, `user_id`, `thread_id`, `hitl_reason` | `hitl_triggered: true` |

**No toggle gate** — runs when `guardrails_router` returns `"hitl"` or triage classifies escalation.

→ See [HITL Handover](../07-messenger-integration/hitl-handover.md).

---

## Node Execution Order

```
entry_node
  → sentiment_node (if toggle)
    → route_query_node
      → [research_plan_node → subquery_node → accumulate_node] OR [retrieval_node]
        → rerank_node
          → inject_product_context_node (if toggle)
            → generate_node
              → guardrails_node (if toggle)
                → [follow_up_node (if toggle)] OR [hitl_node] OR [END]
```

---

## Related Docs

- [Graph Architecture](graph-architecture.md)
- [Retrieval Routing](retrieval-routing.md)
- [Research Mode](research-mode.md)
- [Guardrails Integration](guardrails-integration.md)
- [Node Toggles](../06-ai-customization/node-toggles.md)
