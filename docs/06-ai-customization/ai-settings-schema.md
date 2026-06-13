# AI Settings Schema

Full JSON schema for the `ai_settings` JSONB column on `app.tenants`. Every field is optional — omitted fields inherit global defaults from `app.settings`.

---

## Endpoint

```http
GET /api/workspace/ai-settings
PUT /api/workspace/ai-settings
Authorization: Bearer <manager-jwt>
```

**Required role:** `admin` or `owner`

---

## Full Schema

```json
{
  "scenario_prompts": {
    "intro": "string | null",
    "core": "string | null",
    "checkout": "string | null",
    "hitl": "string | null"
  },
  "node_toggles": {
    "sentiment_node": "boolean",
    "product_context_node": "boolean",
    "sales_tools_node": "boolean",
    "guardrails_node": "boolean",
    "research_mode_node": "boolean",
    "follow_up_node": "boolean"
  },
  "model_params": {
    "temperature": "number",
    "max_tokens": "integer",
    "model_choice": "string"
  }
}
```

---

## Field Reference

### `scenario_prompts`

| Field | Type | Default | Description |
|---|---|---|---|
| `intro` | `string \| null` | `null` | Injected when conversation has 0 prior messages (first turn) |
| `core` | `string \| null` | `null` | Replaces or supplements the global system prompt for mid-conversation turns |
| `checkout` | `string \| null` | `null` | Activated when the sales node triggers a checkout flow |
| `hitl` | `string \| null` | `null` | System context injected into the handover message when HITL is triggered |

When `null`, the corresponding system prompt slot uses the global `system_prompt_id` setting (if set) or the built-in Seina persona default.

→ See [Persona Engine](persona-engine.md) for injection mechanics.

---

### `node_toggles`

| Field | Type | Default | Effect when `false` |
|---|---|---|---|
| `sentiment_node` | `boolean` | `true` | Sentiment analysis skipped; `state.sentiment` stays `null` |
| `product_context_node` | `boolean` | `true` | Product catalog not injected into context |
| `sales_tools_node` | `boolean` | `true` | `generate_checkout_link` / `capture_lead` tools unavailable |
| `guardrails_node` | `boolean` | `true` | Output validation skipped; all responses pass through |
| `research_mode_node` | `boolean` | `true` | Multi-step research disabled; single-pass retrieval only |
| `follow_up_node` | `boolean` | `true` | Follow-up question suggestions not generated |

→ See [Node Toggles](node-toggles.md) for full behavior matrix.

---

### `model_params`

| Field | Type | Default | Validation |
|---|---|---|---|
| `temperature` | `float` | `0.3` | `0.0 – 2.0` |
| `max_tokens` | `integer` | `1024` | `1 – 4096` |
| `model_choice` | `string` | `"llama-3.3-70b-versatile"` | Must be in server-side allowlist |

→ See [Model Parameters](model-parameters.md) for allowlist and override precedence.

---

## Example: Full Settings Object

```json
{
  "scenario_prompts": {
    "intro": "You are Seina, a friendly concierge for Acme Corp. Greet the user warmly and ask how you can help today.",
    "core": "You are a product expert for Acme Corp. Answer questions only about our product catalog. For off-topic questions, politely redirect.",
    "checkout": "The customer is ready to purchase. Guide them through the checkout process step by step.",
    "hitl": "You are being handed off to a human agent. Summarize the conversation so far for the agent."
  },
  "node_toggles": {
    "sentiment_node": true,
    "product_context_node": true,
    "sales_tools_node": true,
    "guardrails_node": true,
    "research_mode_node": false,
    "follow_up_node": true
  },
  "model_params": {
    "temperature": 0.5,
    "max_tokens": 800,
    "model_choice": "llama-3.3-70b-versatile"
  }
}
```

---

## Partial Update

`PUT` performs a deep merge. Fields not included in the request body retain their current values. To reset a field to its default, pass `null` explicitly:

```json
{
  "scenario_prompts": {
    "intro": null
  }
}
```

---

## Validation Errors

| Error | Cause |
|---|---|
| `422 Unprocessable Entity` | `temperature` out of range, `max_tokens` exceeds 4096, unrecognized field |
| `403 Manager role required` | Caller is `member` |
| `400 Model not in allowlist` | `model_choice` not in server's allowed models list |

---

## Storage

Settings are stored as a JSONB column on `app.tenants`:

```sql
ALTER TABLE app.tenants
ADD COLUMN ai_settings JSONB DEFAULT '{}'::jsonb;
```

The API serializes/deserializes via a Pydantic `AiSettings` model. Unknown top-level keys are rejected at validation time.

---

## Related Docs

- [Persona Engine](persona-engine.md)
- [Node Toggles](node-toggles.md)
- [Model Parameters](model-parameters.md)
- [Dynamic Settings](../16-configuration-reference/dynamic-settings.md) — global defaults
