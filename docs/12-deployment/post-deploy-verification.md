# Post-Deploy Verification

Run these checks after every deploy to confirm the application is healthy.

---

## Quick Checklist

```bash
# 1. Service running
sudo systemctl is-active nexus-chat

# 2. HTTP health check
curl -sSI https://chat.nexus.gayo-sphere.cloud/ | head -1

# 3. API health endpoint
curl -s https://chat.nexus.gayo-sphere.cloud/api/health | jq .

# 4. Recent logs (look for errors)
journalctl -u nexus-chat -n 50 --no-pager
```

All four should pass before declaring the deploy successful.

---

## Health Endpoint Response

`GET /api/health` checks all critical dependencies:

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
  "timestamp": "2026-06-13T12:00:00Z"
}
```

Any check returning `"error"` indicates a dependency problem. `status` is `"degraded"` if non-critical checks fail, `"error"` if critical checks (Postgres, Qdrant) fail.

---

## Dependency Health Checks

### Postgres

```bash
# From VPS
psql "postgresql://nexus_rag:password@localhost:5432/nexus_rag" -c "SELECT 1;"
```

### Qdrant

```bash
curl -s http://127.0.0.1:6333/healthz
# Expected: {"title":"qdrant - 200"}
```

### Redis

```bash
redis-cli ping
# Expected: PONG
```

### Docker containers

```bash
docker compose -f infra/docker-compose.yml ps
# All services should show "Up"
```

---

## Functional Smoke Tests

### Login

```bash
TOKEN=$(curl -s -X POST https://chat.nexus.gayo-sphere.cloud/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your_password"}' \
  | jq -r '.access_token')
echo "Token: ${TOKEN:0:20}..."
```

### List workspaces

```bash
curl -s https://chat.nexus.gayo-sphere.cloud/api/tenants \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].name'
```

### Index summary (verify ingest)

```bash
curl -s https://chat.nexus.gayo-sphere.cloud/api/documents/index_summary \
  -H "Authorization: Bearer $TOKEN" | jq '{total_docs, total_chunks}'
```

### SSE chat smoke test

```bash
curl -N -s https://chat.nexus.gayo-sphere.cloud/api/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","conversation_id":"test-123","tenant_id":"your-tenant-id"}' \
  | head -20
# Should see: data: {"type":"status",...} then token events
```

---

## Log Monitoring

```bash
# Live log tail
journalctl -u nexus-chat -f

# Last 100 lines
journalctl -u nexus-chat -n 100 --no-pager

# Errors only
journalctl -u nexus-chat -p err -n 50 --no-pager

# Since last deploy
journalctl -u nexus-chat --since "10 minutes ago"
```

**Red flags to look for in logs:**

| Log pattern | Meaning |
|---|---|
| `Connection refused` to Qdrant/Redis/Postgres | Dependency down |
| `alembic.exc.ProgrammingError` | Migration not applied |
| `HMAC verification failed` | Wrong `MESSENGER_APP_SECRET` |
| `GROQ_API_KEY` errors | Invalid or missing Groq key |
| `Exception in ASGI application` | Application crash — check full traceback |

---

## Rollback Decision

If any of these conditions are true after deploy, rollback:

- `systemctl is-active nexus-chat` → `failed`
- `/api/health` → `"status": "error"`
- Login endpoint returns `500`
- Qdrant chunk count dropped to 0 unexpectedly

→ See [RAG Deployment — Rollback](rag-deployment.md#rollback) for rollback procedure.

---

## Related Docs

- [RAG Deployment](rag-deployment.md)
- [Observability — Health Endpoint](../13-observability/health-endpoint.md)
- [Troubleshooting — Deployment Issues](../17-troubleshooting/deployment-issues.md)
