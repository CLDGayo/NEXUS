# POST /api/chat/stream

Stream a chat response via Server-Sent Events. This is the primary chat endpoint — all responses are streamed token-by-token.

---

## Request

```
POST /api/chat/stream
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

```json
{
  "query": "What is the refund policy?",
  "thread_id": "optional-uuid-for-continuity",
  "surface": "web | messenger | api",
  "stream": true
}
```

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | string | Yes | — | User message, max 4000 chars |
| `thread_id` | string | No | auto-generated UUID | Pass same ID to continue conversation |
| `surface` | string | No | `"web"` | Controls system prompt and node behavior |
| `stream` | bool | No | `true` | Must be `true` for SSE; `false` returns JSON (non-streaming) |

---

## SSE Event Stream

Events arrive in this order:

```
data: {"type": "status", "content": "Retrieving relevant context..."}

data: {"type": "sources", "content": [
  {"title": "Refund Policy", "score": 0.92, "chunk_index": 2}
]}

data: {"type": "token", "content": "Our"}
data: {"type": "token", "content": " refund"}
data: {"type": "token", "content": " policy..."}

data: {"type": "followups", "content": [
  "How do I request a refund?",
  "What is the refund timeline?"
]}

data: {"type": "done", "content": null}
```

| Event type | When | Content type |
|---|---|---|
| `status` | Before retrieval begins | string (status message) |
| `sources` | After rerank, before generation | array of source objects |
| `token` | During generation | string (one token) |
| `followups` | After generation completes | array of suggested questions |
| `done` | Stream end signal | null |
| `error` | On pipeline failure | string (error message) |

---

## Consuming the Stream

```javascript
const response = await fetch('/api/chat/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ query, thread_id })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const chunk = decoder.decode(value);
  for (const line of chunk.split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));
    handleEvent(event);
  }
}
```

---

## Non-Streaming Response

When `stream: false`:

```json
{
  "answer": "Our refund policy allows returns within 30 days [1].",
  "sources": [{ "title": "Refund Policy", "score": 0.92 }],
  "followups": ["How do I request a refund?"],
  "thread_id": "uuid"
}
```

---

## Thread Continuity

`thread_id` maps to LangGraph's `thread_id` for the PostgreSQL checkpointer. Pass the same `thread_id` across turns for multi-turn conversation:

```json
// Turn 1
{ "query": "What is your refund policy?", "thread_id": "sess-abc" }

// Turn 2 (references prior context)
{ "query": "How long does that take?", "thread_id": "sess-abc" }
```

Without `thread_id`, each request is a fresh single-turn exchange.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired JWT / API token |
| `403` | API token lacks `chat` scope |
| `422` | `query` missing or exceeds 4000 chars |
| `503` | Qdrant or Groq unreachable |

---

## nginx Requirement

> **CRITICAL:** nginx must have `proxy_buffering off` for this endpoint, or SSE tokens buffer until the entire response completes. See [nginx configuration](../../12-deployment/nginx-configuration.md).

---

## Related Docs

- [Stage 5 — Generation](../../02-rag-pipeline/stage-5-generation.md)
- [State Persistence](../../08-orchestrator/state-persistence.md)
- [Chat Interface (Frontend)](../../09-frontend/chat-interface.md)
- [POST /api/chat/upload](upload.md)
