# Model Parameters

Per-tenant overrides for LLM inference: temperature, output length cap, and model selection.

---

## Parameters

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `temperature` | `float` | `0.3` | `0.0 – 2.0` | Sampling temperature. Lower = more deterministic; higher = more creative |
| `max_tokens` | `integer` | `1024` | `1 – 4096` | Maximum tokens in the generated response |
| `model_choice` | `string` | `"llama-3.3-70b-versatile"` | Allowlist only | Groq model ID to use for primary generation |

---

## Model Allowlist

`model_choice` is validated server-side against a hard-coded allowlist. Requests with unlisted models return `400 Bad Request`.

| Model ID | Notes |
|---|---|
| `llama-3.3-70b-versatile` | Default primary — best quality |
| `llama-3.1-70b-versatile` | Stable fallback |
| `llama-3.1-8b-instant` | Fast, lower quality — use for high-volume or latency-sensitive workloads |
| `mixtral-8x7b-32768` | Long-context tasks |
| `gemma2-9b-it` | Lightweight alternative |

> **📝 NOTE:** The allowlist is defined in `rag/orchestrator/llm.py`. Adding a new model requires a code change and redeploy — it cannot be configured via env or UI.

---

## Override Precedence

```
Global GROQ_MODEL env var
    ↓ overridden by
app.settings GROQ_MODEL (dynamic setting)
    ↓ overridden by
tenant ai_settings.model_params.model_choice
```

The follow-up model (`llama-3.1-8b-instant`) is always fixed — it is not overridable by tenant AI settings.

---

## Temperature Guidance

| Use case | Recommended temperature |
|---|---|
| FAQ / support bot (exact answers) | `0.0 – 0.2` |
| General product assistant (default) | `0.3` |
| Creative content or storytelling | `0.7 – 1.0` |
| Brainstorming / open-ended | `1.0 – 1.5` |

> **⚠️ WARNING:** Temperatures above `1.0` significantly increase hallucination risk for factual RAG use cases. Guardrails help but do not fully compensate for very high temperatures.

---

## API Usage

```bash
curl -X PUT https://chat.nexus.gayo-sphere.cloud/api/workspace/ai-settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_params": {
      "temperature": 0.2,
      "max_tokens": 600,
      "model_choice": "llama-3.1-8b-instant"
    }
  }'
```

Reset all model params to global defaults:

```bash
curl -X PUT https://chat.nexus.gayo-sphere.cloud/api/workspace/ai-settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_params": {}}'
```

---

## Effect on Latency

| Change | Latency impact |
|---|---|
| `model_choice: llama-3.1-8b-instant` | ~40% faster TTFT vs 70b |
| `max_tokens: 256` | Faster completion; shorter answers |
| `temperature: 0.0` | No measurable impact |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `400 Model not in allowlist` | `model_choice` not in server allowlist | Use a listed model ID from the table above |
| `422` on temperature | Value outside `0.0 – 2.0` | Clamp to valid range |
| Responses still using wrong model | Tenant setting not saved | Verify via `GET /api/workspace/ai-settings` |
| Very short responses | `max_tokens` too low | Increase; 512 is a reasonable minimum for detailed answers |

---

## Related Docs

- [AI Settings Schema](ai-settings-schema.md)
- [Dynamic Settings](../16-configuration-reference/dynamic-settings.md) — global `GROQ_MODEL` default
- [Orchestrator — Generation Node](../08-orchestrator/nodes-reference.md)
