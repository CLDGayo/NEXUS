# n8n Automation

n8n handles the automation layer for three webhook-triggered workflows: checkout link generation, CRM lead capture, and HITL owner notification.

---

## Workflows

| Workflow | Trigger | Action |
|---|---|---|
| Checkout | `POST N8N_WEBHOOK_CHECKOUT_URL` | Create Stripe payment link → return URL |
| Lead capture | `POST N8N_WEBHOOK_LEAD_URL` | Create/update contact in GoHighLevel CRM |
| HITL notify | `POST N8N_WEBHOOK_NOTIFY_URL` | Send email/Slack notification to workspace owner |

---

## Checkout Workflow

**Inbound payload (from NEXUS):**

```json
{
  "product_id": "uuid",
  "product_name": "Pro Package",
  "price": 99.00,
  "currency": "USD",
  "tenant_id": "acme-corp",
  "conversation_id": "thread-uuid"
}
```

**n8n steps:**
1. Receive webhook
2. Call Stripe API: `POST /v1/payment_links` with product price
3. Return `{"checkout_url": "https://buy.stripe.com/..."}`

**Expected response to NEXUS:**
```json
{ "checkout_url": "https://buy.stripe.com/..." }
```

---

## Lead Capture Workflow

**Inbound payload:**

```json
{
  "name": "Alice Smith",
  "email": "alice@example.com",
  "phone": "+1-555-0100",
  "tenant_id": "acme-corp",
  "source": "messenger",
  "metadata": { "product_interest": "Pro Package" }
}
```

**n8n steps:**
1. Receive webhook
2. Search GoHighLevel for existing contact by email
3. Create or update contact record
4. Tag contact with `nexus_lead` + tenant name

**Expected response:** `200 OK` (body ignored by NEXUS)

---

## HITL Notify Workflow

**Inbound payload:**

```json
{
  "event": "hitl_triggered",
  "trigger_source": "user | guardrails | triage",
  "tenant_id": "acme-corp",
  "sender_id": "psid",
  "conversation_id": "thread-uuid",
  "pause_expires_at": "2026-06-14T01:00:00Z"
}
```

**n8n steps:**
1. Receive webhook
2. Look up workspace owner email from `tenant_id` (or hardcoded per workspace)
3. Send email via SMTP / Resend / SendGrid
4. Optionally send Slack message to ops channel

---

## Environment Variables

```bash
N8N_WEBHOOK_CHECKOUT_URL=https://n8n.example.com/webhook/checkout
N8N_WEBHOOK_LEAD_URL=https://n8n.example.com/webhook/lead
N8N_WEBHOOK_NOTIFY_URL=https://n8n.example.com/webhook/hitl-notify
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Checkout link not generated | Webhook URL not set or n8n workflow paused | Check env var; verify n8n workflow is active |
| Timeout on checkout | Stripe API slow or n8n overloaded | NEXUS default timeout 10s; n8n should respond within 5s |
| Lead not in CRM | GoHighLevel API key expired | Rotate API key in n8n credentials |
| HITL email not sent | SMTP credentials expired or wrong template | Check n8n execution logs for email node errors |

---

## Related Docs

- [SDR Persona](../06-ai-customization/sdr-persona.md)
- [HITL Handover](../07-messenger-integration/hitl-handover.md)
- [Sales Tools](../08-orchestrator/sales-tools.md)
