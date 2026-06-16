# LiteLLM Proxy

LiteLLM runs as a Docker container (`nexus-litellm`) and provides a unified OpenAI-compatible API over multiple LLM providers. NEXUS routes Groq calls through it when `LITELLM_BASE_URL` is set.

---

## Purpose

| Capability | Benefit |
|---|---|
| Provider fallback | If Groq is down, route to OpenAI or Anthropic automatically |
| Budget enforcement | Per-key spend limits via LiteLLM's budget manager |
| Request logging | Unified log of all LLM calls across providers |
| Model aliasing | Map `llama-3.3-70b-versatile` to provider-specific model IDs |

---

## Configuration

LiteLLM config lives at `litellm/config.yaml` (mounted into the container):

```yaml
model_list:
  - model_name: llama-3.3-70b-versatile
    litellm_params:
      model: groq/llama-3.3-70b-versatile
      api_key: os.environ/GROQ_API_KEY

  - model_name: llama-3.1-8b-instant
    litellm_params:
      model: groq/llama-3.1-8b-instant
      api_key: os.environ/GROQ_API_KEY

  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY

router_settings:
  routing_strategy: latency-based-routing
  fallbacks:
    - llama-3.3-70b-versatile: [gpt-4o-mini]
```

---

## Environment Variables

```bash
# NEXUS side
LITELLM_BASE_URL=http://127.0.0.1:4000   # VPS: localhost; Mac: optional

# LiteLLM container side (passed via docker-compose env)
GROQ_API_KEY=...
OPENAI_API_KEY=...          # optional — needed only for fallback
LITELLM_MASTER_KEY=...      # required for /health and admin endpoints
```

---

## Docker Compose Service

```yaml
nexus-litellm:
  image: ghcr.io/berriai/litellm:main-latest
  ports:
    - "4000:4000"
  volumes:
    - ./litellm/config.yaml:/app/config.yaml
  command: --config /app/config.yaml --port 4000
  environment:
    GROQ_API_KEY: ${GROQ_API_KEY}
    LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
```

---

## Fallback Behavior

When primary model fails (5xx or timeout):

1. LiteLLM retries primary once
2. Falls back to next model in `fallbacks` list
3. Returns response via same OpenAI-compatible API surface

NEXUS `rag/orchestrator/llm.py` does not need to change — it calls `LITELLM_BASE_URL` with the same model name; LiteLLM handles routing.

---

## Health Check

```bash
# Check LiteLLM is reachable
curl http://127.0.0.1:4000/health \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# Check model availability
curl http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `NEXUS: LiteLLM connection refused` | Container not running | `docker compose restart nexus-litellm` |
| Fallback fires every request | Groq API key invalid | Verify `GROQ_API_KEY` in container env |
| `No model found: llama-3.3-70b-versatile` | Config not mounted | Check volume mount in docker-compose; restart |
| High latency (>3s TTFT) | Routing to fallback OpenAI model | Check Groq status; latency is expected for OpenAI path |

---

## Related Docs

- [Docker Compose Guide](../12-deployment/docker-compose-guide.md)
- [Environment Setup](../12-deployment/environment-setup.md)
- [Performance Issues](../17-troubleshooting/performance-issues.md)
