# Sales Tools

Three LLM-callable tools activate the commerce flow: inventory check, checkout link generation, and CRM lead capture. All require `sales_tools_node` toggle enabled.

---

## Tools

### `check_inventory`

Verifies a product exists in the catalog and is active before generating a checkout link.

**Called by:** LLM when user expresses purchase intent for a named product.

**Parameters:**

```json
{
  "product_name": "string"
}
```

**Returns:**

```json
{
  "found": true,
  "product_id": "uuid",
  "product_name": "Pro Package",
  "price": 99.00,
  "currency": "USD",
  "is_active": true
}
```

If `found = false` or `is_active = false`, the LLM is instructed to inform the user the product is unavailable rather than generating a checkout link.

---

### `generate_checkout_link`

Calls the n8n checkout webhook to generate a Stripe payment link.

**Called by:** LLM after `check_inventory` confirms product availability.

**Parameters:**

```json
{
  "product_id": "uuid",
  "product_name": "Pro Package",
  "price": 99.00,
  "currency": "USD"
}
```

**n8n webhook payload sent to `N8N_WEBHOOK_CHECKOUT_URL`:**

```json
{
  "product_id": "uuid",
  "product_name": "Pro Package",
  "price": 99.00,
  "currency": "USD",
  "tenant_id": "acme-corp",
  "user_id": "psid-or-user-uuid",
  "conversation_id": "thread-uuid"
}
```

**Expected response from n8n:**

```json
{
  "checkout_url": "https://buy.stripe.com/..."
}
```

**Returns to LLM:** `checkout_url` string, embedded in the response as a clickable link.

---

### `capture_lead`

Extracts and pushes contact information to CRM via n8n.

**Called by:** LLM when user shares name + email or phone, or post-checkout.

**Parameters:**

```json
{
  "name": "string",
  "email": "string | null",
  "phone": "string | null"
}
```

**n8n webhook payload sent to `N8N_WEBHOOK_LEAD_URL`:**

```json
{
  "name": "Alice Smith",
  "email": "alice@example.com",
  "phone": "+1-555-0100",
  "tenant_id": "acme-corp",
  "source": "messenger",
  "conversation_id": "thread-uuid",
  "metadata": {
    "product_interest": "Pro Package",
    "intent_score": 0.87
  }
}
```

**Returns to LLM:** `{"status": "captured"}` — LLM confirms to user their details were saved.

---

## Tool Registration

Tools are bound to the LLM client in `generate_node` when `sales_tools_node` is enabled:

```python
tools = []
if state["ai_settings"].node_toggles.sales_tools_node:
    tools = [check_inventory, generate_checkout_link, capture_lead]

response = await llm.with_tools(tools).ainvoke(messages)
```

When the LLM calls a tool, LangGraph handles the tool execution loop before continuing generation.

---

## Dedup Gate

`generate_checkout_link` checks the last 3 assistant messages before generating a new link. If a checkout URL for the same product already appears in recent messages, the tool returns the existing URL rather than generating a new Stripe link.

This prevents duplicate payment links from cluttering the conversation.

---

## Error Handling

| Error | LLM fallback message |
|---|---|
| n8n checkout webhook timeout | "I'm having trouble generating the link right now. Please try again in a moment." |
| n8n returns non-200 | "I wasn't able to create a checkout link. Please contact support." |
| `check_inventory` → not found | "I don't see that product in our current catalog." |
| `capture_lead` fails | Silent failure — lead logged as failed, user sees no error |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Checkout link not generated | `N8N_WEBHOOK_CHECKOUT_URL` not set | Add env var; restart service |
| Lead not in CRM | `N8N_WEBHOOK_LEAD_URL` not set or n8n paused | Check env var; verify n8n workflow active |
| LLM not calling tools | `sales_tools_node` toggle off | Enable toggle in AI settings |
| Duplicate checkout links | Dedup gate bypassed | Check message count in `NexusState`; verify last-3 window logic |

---

## Related Docs

- [SDR Persona](../06-ai-customization/sdr-persona.md) — persona + scenario prompts for sales mode
- [Product Context](product-context.md) — product catalog injection
- [Node Toggles](../06-ai-customization/node-toggles.md)
- [n8n Automation](../10-integrations/n8n-automation.md)
