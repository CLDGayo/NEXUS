# Langfuse

Langfuse provides LLM-specific tracing: token usage, latency, generation quality, and prompt versioning per conversation turn. It is optional — NEXUS functions normally without it.

---

## Activation

Set environment variables to enable:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # or self-hosted URL
```

If `LANGFUSE_PUBLIC_KEY` is not set, the Langfuse integration is a no-op.

---

## What Is Traced

| Event | Langfuse trace object |
|---|---|
| Each conversation turn | Top-level `Trace` keyed by `conversation_id` |
| Primary LLM generation | `Generation` span inside the trace |
| Follow-up generation | Second `Generation` span |
| Retrieval stage | `Span` with chunk count + RRF scores |
| Guardrails validation | `Span` with pass/fail + validator name |

---

## Trace Structure

```
Trace: {conversation_id}
  metadata:
    tenant_id: "acme-corp"
    surface: "web"
    user_id: "user-uuid"
  
  Span: retrieval_node
    input: {query: "...", tenant_id: "..."}
    output: {chunk_count: 12, top_score: 0.89}
    latency: 320ms
  
  Generation: generate_node
    model: "llama-3.3-70b-versatile"
    input: [{role: "system", ...}, {role: "user", ...}]
    output: "..."
    usage: {prompt_tokens: 1842, completion_tokens: 312}
    latency: 1.2s
  
  Generation: follow_up_node
    model: "llama-3.1-8b-instant"
    output: ["...", "...", "..."]
    usage: {prompt_tokens: 420, completion_tokens: 85}
    latency: 380ms
```

---

## Scores

Langfuse scores can be posted after guardrails validation to track response quality over time:

```python
langfuse.score(
    trace_id=trace_id,
    name="guardrails_passed",
    value=1.0 if result.passed else 0.0,
    comment=result.reason
)
```

This enables quality dashboards showing pass rates per tenant, per model, and over time.

---

## Dashboard Queries

Useful Langfuse dashboard filters:

| Filter | Use |
|---|---|
| `metadata.tenant_id = "acme-corp"` | Per-workspace analysis |
| `metadata.surface = "messenger"` | Messenger-specific performance |
| `model = "llama-3.1-8b-instant"` | Follow-up model cost tracking |
| `scores.guardrails_passed < 1` | Failed generations audit |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No traces in Langfuse | Keys not set or wrong host | Verify `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_HOST` |
| Traces missing token usage | Groq response not including usage | Check Groq API response; `stream=True` may omit usage |
| Duplicate traces | Multiple workers each creating trace | Use `trace_id = conversation_id` (deterministic) to deduplicate |

---

## Related Docs

- [OpenTelemetry](opentelemetry.md) — infrastructure-level tracing
- [Environment Setup](../12-deployment/environment-setup.md) — Langfuse env vars
- [Stage 5 — Generation](../02-rag-pipeline/stage-5-generation.md)
