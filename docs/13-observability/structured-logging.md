# Structured Logging

NEXUS emits structured JSON logs to stdout, captured by systemd's journald. PII is redacted before write. Audit events (role changes, HITL triggers, token revocations) are also persisted to `app.logs` in Postgres.

---

## Log Format

Every log line is a JSON object:

```json
{
  "timestamp": "2026-06-13T12:00:00.123Z",
  "level": "INFO",
  "logger": "rag.routers.chat",
  "event": "chat_turn_complete",
  "tenant_id": "acme-corp",
  "user_id": "550e8400-...",
  "conversation_id": "thread-uuid",
  "surface": "web",
  "duration_ms": 1842,
  "chunk_count": 8,
  "route": "direct",
  "guardrail_passed": true
}
```

---

## Log Levels

| Level | Used for |
|---|---|
| `DEBUG` | Retrieval scores, chunk payloads, internal state (dev only) |
| `INFO` | Request completion, node execution, normal operations |
| `WARNING` | Degraded state, non-critical failures, rate limit approach |
| `ERROR` | Exceptions, failed dependency calls, unhandled errors |
| `CRITICAL` | Service cannot start, data integrity issues |

Production runs at `INFO`. Set `LOG_LEVEL=DEBUG` in `.env` for verbose output (not recommended in production — log volume is high).

---

## Key Log Events

| `event` | Level | When emitted |
|---|---|---|
| `chat_turn_complete` | `INFO` | Each chat turn finishes |
| `retrieval_complete` | `INFO` | Retrieval node finishes |
| `guardrail_failed` | `WARNING` | Response fails validation |
| `hitl_triggered` | `WARNING` | HITL handover activated |
| `rate_limited` | `WARNING` | Messenger sender rate limited |
| `signature_mismatch` | `ERROR` | Webhook HMAC verification failed |
| `ingest_complete` | `INFO` | Vault ingest finishes |
| `migration_applied` | `INFO` | Alembic revision applied |
| `service_startup` | `INFO` | uvicorn process starts |

---

## PII Redaction

Before any log is written to stdout or `app.logs`, the PII filter runs:

```python
PII_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"(\+?1?\s?)?(\d{3}[\s.-]?\d{3}[\s.-]?\d{4})",
    "credit_card": r"\b(?:\d{4}[\s-]?){3}\d{4}\b",
}
```

Matches are replaced with `[EMAIL]`, `[PHONE]`, `[CARD]`. The original values are never written to logs.

---

## Audit Log (Postgres)

Security-relevant events are persisted to `app.logs` for queryable audit history:

| Event type | Trigger |
|---|---|
| `role_change` | Member role updated |
| `member_removed` | Member removed from workspace |
| `invite_created` | Workspace invite sent |
| `invite_accepted` | Invite accepted, member joined |
| `api_token_created` | New API token issued |
| `api_token_revoked` | API token deleted |
| `hitl_triggered` | HITL handover activated |
| `ownership_transferred` | Workspace owner changed |

Query the audit log:

```bash
curl https://chat.nexus.gayo-sphere.cloud/api/logs \
  -H "Authorization: Bearer $TOKEN" \
  -G --data-urlencode "event_type=role_change" \
     --data-urlencode "limit=50"
```

Requires `admin` or `owner` role.

---

## journalctl Queries

```bash
# All logs, live tail
journalctl -u nexus-chat -f

# Errors and above
journalctl -u nexus-chat -p err -n 50

# Last hour
journalctl -u nexus-chat --since "1 hour ago"

# Search for specific event
journalctl -u nexus-chat | grep "signature_mismatch"

# JSON output (for log shipper)
journalctl -u nexus-chat -o json | head -5
```

---

## Log Shipping (Optional)

For centralized log aggregation, ship from journald to a log platform:

```bash
# Fluent Bit example: tail journald → Loki
[INPUT]
    Name systemd
    Tag nexus.*
    Systemd_Filter _SYSTEMD_UNIT=nexus-chat.service

[OUTPUT]
    Name loki
    Match nexus.*
    Host loki.example.com
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No logs in journalctl | Service not running | `systemctl status nexus-chat` |
| PII appearing in logs | Redaction filter not in log pipeline | Verify `PiiFilter` is registered as a log handler |
| Audit log empty | Query needs manager role | Use admin JWT; check `Authorization` header |
| Log volume too high | `LOG_LEVEL=DEBUG` in production | Set `LOG_LEVEL=INFO` in `.env`; restart |

---

## Related Docs

- [Health Endpoint](health-endpoint.md)
- [OpenTelemetry](opentelemetry.md)
- [Security & PII](../07-messenger-integration/security-pii.md)
- [Post-Deploy Verification](../12-deployment/post-deploy-verification.md)
