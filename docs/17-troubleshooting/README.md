# Troubleshooting

Diagnostic runbook index for NEXUS. Each guide covers symptoms, root causes, and resolutions for a specific subsystem.

---

## Diagnostic Runbook

Before opening a specific guide, collect:

```bash
# 1. Service status
sudo systemctl is-active nexus-chat
sudo systemctl status nexus-chat --no-pager

# 2. Recent errors
journalctl -u nexus-chat -p err -n 50 --no-pager

# 3. Dependency health
curl -s https://chat.nexus.gayo-sphere.cloud/api/health | jq .

# 4. Docker containers
docker compose -f infra/docker-compose.yml ps

# 5. Disk space
df -h /home
```

---

## Guide Index

| Guide | Symptoms covered |
|---|---|
| [RAG Pipeline Issues](rag-pipeline-issues.md) | Low recall, hallucination, abstentions, BM25 cold start |
| [Authentication Issues](authentication-issues.md) | JWT expiry, token scope errors, tenant auth failures |
| [Messenger Issues](messenger-issues.md) | Webhook 403, HMAC fail, HITL stuck, retry exhaustion |
| [Deployment Issues](deployment-issues.md) | Migration drift, container health fail, fastembed cache |
| [Performance Issues](performance-issues.md) | BM25 rebuild latency, Qdrant cold start, slow TTFT |

---

## Quick Reference — Common Errors

| Error | Guide |
|---|---|
| `401 Unauthorized` on API | [Authentication Issues](authentication-issues.md) |
| `403 Manager role required` | [Authentication Issues](authentication-issues.md) |
| `502 Bad Gateway` | [Deployment Issues](deployment-issues.md) |
| `503` from health endpoint | [Deployment Issues](deployment-issues.md) |
| Bot not replying on Messenger | [Messenger Issues](messenger-issues.md) |
| Citations missing or phantom | [RAG Pipeline Issues](rag-pipeline-issues.md) |
| TTFT > 5 seconds | [Performance Issues](performance-issues.md) |
| `alembic.exc.ProgrammingError` | [Deployment Issues](deployment-issues.md) |

---

## Related Docs

- [Deployment — Post-Deploy Verification](../12-deployment/post-deploy-verification.md)
- [Observability — Health Endpoint](../13-observability/health-endpoint.md)
- [Observability — Structured Logging](../13-observability/structured-logging.md)
