# AI Settings API

Read and update tenant-scoped AI customization settings: scenario prompts, node toggles, and model parameters.

---

## GET /api/workspace/ai-settings

Return the merged AI settings for the current workspace — per-tenant overrides merged over system defaults.

```
GET /api/workspace/ai-settings
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

### Response

```json
{
  "scenario_prompts": {
    "sales": "You are a helpful sales assistant for {tenant_name}...",
    "support": "You help customers resolve issues..."
  },
  "active_nodes": {
    "sentiment": true,
    "graph_retrieval": true,
    "product_context": true,
    "cart_recovery": false,
    "research_mode": false,
    "sales_tools": true
  },
  "model_params": {
    "model_choice": "llama-3.3-70b-versatile",
    "temperature": 0.3,
    "max_tokens": 1024
  },
  "available_models": [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
  ]
}
```

| Field | Notes |
|---|---|
| `scenario_prompts` | Per-surface system prompt overrides; `null` values fall back to global defaults |
| `active_nodes` | 6 toggleable LangGraph nodes; `false` = node skipped at runtime |
| `model_params` | LLM parameters; `model_choice` validated against `available_models` |
| `available_models` | Read-only list of allowed model IDs; included so UI renders Select without a second request |

---

## PUT /api/workspace/ai-settings

Partially update AI settings. Only supplied keys are updated — unset siblings survive.

```
PUT /api/workspace/ai-settings
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

```json
{
  "model_params": {
    "temperature": 0.7,
    "max_tokens": 2048
  }
}
```

All three top-level keys (`scenario_prompts`, `active_nodes`, `model_params`) are optional. The server deep-merges one level: supplying `{"model_params": {"temperature": 0.7}}` updates only `temperature` — `model_choice` and `max_tokens` are preserved.

### Validation Rules

| Field | Constraint | Error on violation |
|---|---|---|
| `model_params.temperature` | `0.0 – 2.0` | `422 Unprocessable Entity` |
| `model_params.max_tokens` | `64 – 8192` | `422 Unprocessable Entity` |
| `model_params.model_choice` | Must be in `available_models` | `400 Bad Request` (runtime check, not Pydantic) |

### Response

Returns the full merged settings object after update (same schema as GET).

---

## Permissions

Both endpoints require `require_owner`. Admins and members cannot read or write AI settings.

---

## Override Precedence

```
System defaults (config.py)
  ↓ overridden by
Dynamic settings (app.settings table — global SETTING_KEYS)
  ↓ overridden by
Tenant AI settings (app.tenants.ai_settings JSONB — per-workspace)
  ↓ used at runtime by
LangGraph orchestrator nodes
```

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Admin or member role; requires owner |
| `400` | `model_choice` not in `available_models` |
| `422` | `temperature` or `max_tokens` out of bounds |

---

## Related Docs

- [AI Customization — Overview](../../06-ai-customization/README.md)
- [AI Settings Schema](../../06-ai-customization/ai-settings-schema.md)
- [Node Toggles](../../06-ai-customization/node-toggles.md)
- [Model Parameters](../../06-ai-customization/model-parameters.md)
- [Dynamic Settings](../../16-configuration-reference/dynamic-settings.md)
