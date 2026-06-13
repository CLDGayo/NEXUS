# Health Endpoint

`GET /api/health` provides a real-time liveness and dependency readiness check. Used by deploy scripts, monitoring systems, and the post-deploy verification runbook.

---

## Endpoint

```http
GET /api/health
```

No authentication required. Returns `200` when healthy, `503` when one or more critical checks fail.

---

## Response Format

```json
{
  "status": "ok",
  "checks": {
    "postgres": "ok",
    "qdrant": "ok",
    "redis": "ok",
    "litellm": "ok"
  },
  "version": "1.0.0",
  "uptime_seconds": 3842,
  "timestamp": "2026-06-13T12:00:00Z"
}
```

---

## Status Values

| `status` | Meaning | HTTP code |
|---|---|---|
| `"ok"` | All critical checks pass | `200` |
| `"degraded"` | Non-critical checks failing; app functional | `200` |
| `"error"` | Critical check (Postgres or Qdrant) failing | `503` |

---

## Individual Check Details

### `postgres`

Runs `SELECT 1` against the configured `DATABASE_URL`.

| Result | Meaning |
|---|---|
| `"ok"` | Query succeeded |
| `"error: connection refused"` | Postgres down or wrong connection string |
| `"error: timeout"` | Postgres overloaded or network issue |

---

### `qdrant`

Calls `GET http://127.0.0.1:6333/healthz`.

| Result | Meaning |
|---|---|
| `"ok"` | Qdrant container running and healthy |
| `"error: connection refused"` | Docker container stopped |
| `"error: timeout"` | Qdrant overloaded or loading index |

---

### `redis`

Sends `PING` to Redis.

| Result | Meaning |
|---|---|
| `"ok"` | Redis responding |
| `"error"` | Redis container stopped or connection refused |

---

### `litellm`

Calls `GET http://127.0.0.1:4000/health` (LiteLLM's own health endpoint).

| Result | Meaning |
|---|---|
| `"ok"` | LiteLLM proxy running |
| `"error"` | Container stopped |
| `"skipped"` | `LITELLM_PROXY_URL` not configured |

LiteLLM is non-critical — its failure sets `status: "degraded"` not `"error"`.

---

## Degraded vs Error

| Failing check | `status` |
|---|---|
| Postgres | `"error"` |
| Qdrant | `"error"` |
| Redis | `"error"` |
| LiteLLM | `"degraded"` |

The distinction matters for alerting: `503` triggers a PagerDuty-style alert; `200 degraded` is a warning.

---

## Using in Scripts

```bash
# Wait for service to be healthy (post-deploy)
until curl -sf https://chat.nexus.gayo-sphere.cloud/api/health | jq -e '.status == "ok"' > /dev/null; do
  echo "Waiting for health..."
  sleep 3
done
echo "Service healthy."
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `503` after deploy | Dependency down or migration failed | Check individual check values; fix failing service |
| `"qdrant": "error"` | Docker container stopped | `docker compose start qdrant-nexus` |
| `"postgres": "timeout"` | Long-running migration in progress | Wait for migration to complete; retry |
| Health returns `200` but chat fails | Application error not caught by health check | Check `journalctl -u nexus-chat` for runtime errors |

---

## Related Docs

- [Post-Deploy Verification](../12-deployment/post-deploy-verification.md)
- [Structured Logging](structured-logging.md)
- [Docker Compose Guide](../12-deployment/docker-compose-guide.md)
