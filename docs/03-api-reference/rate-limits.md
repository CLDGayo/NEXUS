# Rate Limits

NEXUS enforces rate limits at both the HTTP API layer and the Messenger integration layer to protect infrastructure and maintain service quality.

---

## HTTP API Rate Limits

> **📝 NOTE:** HTTP-level rate limiting is enforced by the nginx reverse proxy on the VPS. Limits below reflect the default nginx configuration. Local dev instances have no rate limits.

| Route group | Limit | Window |
|---|---|---|
| `POST /api/auth/jwt/login` | 10 requests | 60 seconds per IP |
| `POST /api/chat/stream` | 60 requests | 60 seconds per authenticated user |
| `POST /api/documents/upload` | 20 requests | 60 seconds per authenticated user |
| `POST /api/tenants/{id}/invites` | 10 requests | 60 seconds per authenticated user |
| All other `/api/*` endpoints | 200 requests | 60 seconds per authenticated user |

When a limit is exceeded, the server returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 45
Content-Type: application/json

{"detail": "Rate limit exceeded. Retry after 45 seconds."}
```

The `Retry-After` header indicates the number of seconds to wait before retrying.

---

## Messenger Rate Limits

The Messenger integration applies per-sender rate limiting via Redis to prevent a single user from flooding the LangGraph pipeline:

| Parameter | Default | Configuration |
|---|---|---|
| Max messages per minute | 60 | `MESSENGER_RATE_LIMIT_PER_MIN` env var |
| Message coalesce window | 1500 ms | `MESSENGER_COALESCE_WINDOW_MS` env var |

**Coalescing:** If a sender sends multiple messages within the coalesce window, they are merged into a single request to the LangGraph pipeline. This prevents rapid follow-up messages from creating duplicate processing threads.

**Rate exceeded behavior:** Messages arriving above the per-minute limit are silently dropped (no error reply sent to the user). The sender continues normally after the window resets.

---

## Groq API Limits (Upstream)

NEXUS does not enforce Groq rate limits itself — these are enforced by the Groq API. When Groq returns a 429, NEXUS propagates it as a 500 with a descriptive message.

| Model | Requests/min | Tokens/min |
|---|---|---|
| `llama-3.3-70b-versatile` | 30 | 6,000 |
| `llama-3.1-8b-instant` | 30 | 20,000 |

> **💡 PRO TIP:** If you're hitting Groq token limits, reduce `TOP_K` via `PATCH /api/settings` to lower the number of retrieved chunks passed per generation request. Each chunk is typically 300–500 tokens.

---

## Qdrant Limits

Qdrant imposes soft limits on concurrent requests and collection sizes. The NEXUS deployment uses a single collection (`nexus-vault`) with multi-tenant payload filtering. No per-request Qdrant rate limits are enforced by NEXUS — if Qdrant becomes overwhelmed, it returns connection errors which surface as 500s.

---

## Best Practices for API Consumers

1. **Implement exponential backoff** on 429 and 500 responses. Suggested: start at 1 second, double up to 30 seconds, max 5 retries.
2. **Cache JWT tokens** until 5 minutes before expiry (lifetime: 3600s). Don't re-login on every request.
3. **Stream chat responses** with SSE rather than polling conversation history to minimize request count.
4. **Batch document uploads** where possible — the reconcile endpoint (`POST /api/documents/reconcile`) re-syncs the entire vault in a single request.

---

## Related Docs

- [Errors & Status Codes](errors-and-status-codes.md)
- [Messenger Rate Limits & Coalescing](../07-messenger-integration/rate-limits-coalescing.md)
- [Nginx Configuration](../12-deployment/nginx-configuration.md)
