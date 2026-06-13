# OpenTelemetry

NEXUS emits distributed traces via OpenTelemetry. Spans cover FastAPI request handling, Qdrant queries, Groq LLM calls, and custom RAG pipeline stages.

---

## Configuration

OTel is configured via environment variables:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # gRPC OTLP collector
OTEL_SERVICE_NAME=nexus-chat
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

If `OTEL_EXPORTER_OTLP_ENDPOINT` is not set, OTel tracing is disabled — no performance impact.

---

## Auto-Instrumentation

The following libraries are auto-instrumented via `opentelemetry-bootstrap`:

| Library | Spans produced |
|---|---|
| FastAPI / Starlette | HTTP request span per endpoint |
| SQLAlchemy | Database query spans |
| `httpx` | Outbound HTTP calls (Groq, n8n webhooks) |
| `redis-py` | Redis command spans |

---

## `@traced` Decorator

Custom spans wrap key RAG pipeline stages:

```python
from rag.observability import traced

@traced("retrieval_node")
async def retrieval_node(state: NexusState) -> NexusState:
    ...
```

The decorator creates a child span under the current request trace. Span attributes include `tenant_id`, `surface`, and node-specific metrics (chunk count, scores).

---

## Span Hierarchy

```
HTTP POST /api/chat/stream
  └─ entry_node
  └─ sentiment_node
  └─ route_query_node
  └─ retrieval_node
      └─ qdrant.search (dense arm)
      └─ bm25.search (sparse arm)
      └─ postgres.query (graph arm)
  └─ rerank_node
  └─ generate_node
      └─ http.request (Groq API)
  └─ guardrails_node
  └─ follow_up_node
```

---

## Collector Setup

NEXUS exports to an OTLP gRPC collector. Example Docker Compose addition:

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:latest
  ports:
    - "4317:4317"   # gRPC OTLP
    - "4318:4318"   # HTTP OTLP
  volumes:
    - ./otel/collector.yaml:/etc/otel-collector-config.yaml
  command: ["--config=/etc/otel-collector-config.yaml"]
```

`otel/collector.yaml` routes to your preferred backend (Jaeger, Grafana Tempo, Honeycomb, etc.).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No traces appearing | Collector not running or wrong endpoint | Check `OTEL_EXPORTER_OTLP_ENDPOINT`; verify collector container |
| Missing span attributes | `@traced` not applied to node | Add decorator to node function |
| High latency from OTel | Synchronous export in hot path | Use async OTLP exporter (default in `opentelemetry-exporter-otlp-proto-grpc`) |

---

## Related Docs

- [Langfuse](langfuse.md) — LLM-specific tracing
- [Structured Logging](structured-logging.md)
- [Environment Setup](../12-deployment/environment-setup.md)
