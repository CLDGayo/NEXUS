# Integration Event Model

The integration event bus routes application events to external providers (n8n, Slack, Discord) via `dispatcher.py`. Events are fired in-process, async, after the triggering action completes.

---

## Event Names

| Event | When fired | Typical subscribers |
|---|---|---|
| `hitl_triggered` | HITL pause key set in Redis | n8n notify, Slack, Discord |
| `checkout_completed` | Stripe payment link returned | Slack, Discord |
| `lead_captured` | CRM contact created/updated | Slack, Discord |
| `member_invited` | Invite token created | n8n (email delivery) |
| `member_joined` | Invite accepted | Slack |
| `workspace_archived` | Tenant archived | Slack |
| `document_ingested` | Document chunk count committed | (optional) Slack |

---

## Event Payload Schema

All events share a common envelope:

```json
{
  "event": "EVENT_NAME",
  "tenant_id": "acme-corp",
  "timestamp": "2026-06-14T01:00:00Z",
  "payload": { ... }
}
```

`payload` is event-specific. See each event in the table above for expected payload fields.

---

## Dispatcher

`rag/integrations/dispatcher.py` receives an event dict, loads active integration configs for the tenant from `app.integrations`, and calls each subscribed provider:

```python
async def dispatch(event: str, tenant_id: str, payload: dict):
    integrations = await load_active_integrations(tenant_id, event)
    for integration in integrations:
        provider = get_provider(integration.provider)
        await provider.send(event, payload, integration.config)
```

Failures in one provider do not block others — each call is wrapped in a try/except and logged.

---

## Integration Config Schema

Stored in `app.integrations` JSONB `config` column per provider:

| Provider | Required config fields |
|---|---|
| `n8n` | `webhook_url`, `events: []` |
| `slack` | `webhook_url`, `events: []` |
| `discord` | `webhook_url`, `events: []` |
| `messenger` | `page_id`, `page_token` |

---

## Adding a Subscription

```bash
# Subscribe Slack to HITL events for tenant "acme-corp"
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "provider": "slack",
    "config": {
      "webhook_url": "https://hooks.slack.com/...",
      "events": ["hitl_triggered", "checkout_completed"]
    }
  }'
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Provider webhook 4xx | Log `dispatch_failed`, do not retry |
| Provider webhook 5xx | Retry up to 3× with 5s/30s/120s backoff |
| Provider not configured | Event silently skipped (no active integration for that event) |
| `dispatch` called with unknown `event` | Logged as warning, skipped |

---

## Related Docs

- [n8n Automation](n8n-automation.md)
- [Slack & Discord](slack-discord.md)
- [HITL Handover](../07-messenger-integration/hitl-handover.md)
- [API Reference — Integrations](../03-api-reference/integrations/integrations.md)
