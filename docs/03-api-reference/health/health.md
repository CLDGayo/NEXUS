# Health Endpoints

Liveness and readiness probes for the NEXUS RAG service. Used by load balancers, uptime monitors, and deployment verification scripts.

---

## GET /api/health

Liveness probe. Checks whether the FastAPI process is alive and can reach its critical dependencies.

```
GET /api/health
```

No authentication required — this endpoint is public.

### Response (healthy)

```json
{
  "status": "ok",
  "version": "2.0.0",
  "checks": {
    "qdrant": "ok",
    "postgres": "ok",
    "groq": "ok"
  },
  "uptime_seconds": 84321
}
```

### Response (degraded)

```json
{
  "status": "degraded",
  "version": "2.0.0",
  "checks": {
    "qdrant": "ok",
    "postgres": "ok",
    "groq": "error: connection timeout"
  },
  "uptime_seconds": 84321
}
```

HTTP status is `200` for both `"ok"` and `"degraded"` — the caller should inspect `status` and individual `checks`. HTTP `503` is returned only when Postgres itself is unreachable (the system cannot serve any requests).

---

## GET /api/health/ready

Readiness probe. Returns `200` only when all dependencies are healthy and the system can handle requests. Used by Kubernetes readiness checks or nginx upstream health probes.

```
GET /api/health/ready
```

No authentication required.

### Response

```json
{ "ready": true }
```

Returns `503` when any dependency is unavailable.

---

## Dependency Check Matrix

| Dependency | Probe method | Failure impact |
|---|---|---|
| Qdrant | Count collection points | Retrieval fails; chat returns empty sources |
| Postgres | `SELECT 1` on asyncpg pool | Auth, history, and all writes fail |
| Groq | HEAD to Groq API | Generation fails; chat returns `503` |
| Redis | PING | Messenger HITL and coalescing fail (non-fatal for core chat) |
| Reranker | Import probe (`reranker_import_probe()`) | Reranking skipped; retrieval degrades to RRF-only |

---

## Messenger Surface Health

The Messenger subsystem has its own health endpoint at `/health` (not `/api/health`):

```
GET /health
```

Returns liveness + readiness for: Postgres, Qdrant, Redis, LiteLLM proxy, and the cross-encoder reranker.

---

## Post-Deploy Verification

```bash
# Quick liveness check
curl -sSI https://chat.nexus.gayo-sphere.cloud/api/health

# Full JSON check
curl -s https://chat.nexus.gayo-sphere.cloud/api/health | python3 -m json.tool

# Readiness (expect 200)
curl -o /dev/null -w "%{http_code}" https://chat.nexus.gayo-sphere.cloud/api/health/ready
```

> **💡 PRO TIP:** Add these to `deploy-rag.sh` post-deploy step. If `/api/health/ready` returns non-200, the deploy script should exit non-zero and alert.

---

## Related Docs

- [Post-Deploy Verification](../../12-deployment/post-deploy-verification.md)
- [Observability Overview](../../13-observability/README.md)
- [Structured Logging](../../13-observability/structured-logging.md)
