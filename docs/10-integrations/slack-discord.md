# Slack & Discord

Slack and Discord integrations receive event subscription notifications via incoming webhooks. Both are outbound-only from NEXUS — no incoming message handling.

---

## Supported Events

| Event | Default message |
|---|---|
| `hitl_triggered` | `[NEXUS] Human handover requested — {tenant_id} / {sender_id}` |
| `checkout_completed` | `[NEXUS] Checkout link sent — product: {product_name}, tenant: {tenant_id}` |
| `lead_captured` | `[NEXUS] Lead captured — {name} ({email}), tenant: {tenant_id}` |
| `member_joined` | `[NEXUS] {email} joined workspace {tenant_id}` |
| `workspace_archived` | `[NEXUS] Workspace {tenant_id} archived` |

---

## Slack Setup

**1. Create incoming webhook:**
- Slack App Directory → Incoming Webhooks → Add to Slack
- Select channel → Copy webhook URL

**2. Register integration in NEXUS:**

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "slack",
    "config": {
      "webhook_url": "https://hooks.slack.com/services/...",
      "events": ["hitl_triggered", "checkout_completed", "lead_captured"]
    }
  }'
```

**Payload sent to Slack:**
```json
{ "text": "[NEXUS] Human handover requested — acme-corp / psid_12345" }
```

---

## Discord Setup

**1. Create webhook:**
- Discord channel → Edit Channel → Integrations → Webhooks → New Webhook
- Copy webhook URL

**2. Register integration:**

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "discord",
    "config": {
      "webhook_url": "https://discord.com/api/webhooks/...",
      "events": ["hitl_triggered"]
    }
  }'
```

**Payload sent to Discord:**
```json
{ "content": "[NEXUS] Human handover requested — acme-corp / psid_12345" }
```

> Discord uses `content` field; Slack uses `text`. The dispatcher handles this difference per provider.

---

## Limitations

- Outbound only — NEXUS does not read Slack/Discord messages
- No rich formatting (embeds, blocks) in current implementation — plain text only
- One webhook URL per integration record; create multiple records for multiple channels

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No Slack message on HITL | Event not in `events` list | Update integration config to include `hitl_triggered` |
| `410 Gone` from Slack | Webhook URL deleted | Recreate webhook in Slack; update integration config |
| Discord `400 Bad Request` | Malformed payload | Check `content` field is a non-empty string |
| Events firing but no message | Integration `is_active=false` | `PATCH /api/integrations/{id}` with `{"is_active": true}` |

---

## Related Docs

- [Integration Event Model](integration-event-model.md)
- [HITL Handover](../07-messenger-integration/hitl-handover.md)
- [API Reference — Integrations](../03-api-reference/integrations/integrations.md)
