# Conversations

Conversations map to LangGraph `thread_id` values. Each conversation stores multi-turn history via the PostgreSQL checkpointer.

---

## List Conversations

```
GET /api/conversations
Authorization: Bearer {jwt_token}
```

**Query parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `limit` | integer | 20 | Max 100 |
| `offset` | integer | 0 | Pagination offset |
| `surface` | string | — | Filter by `web`, `messenger`, `api` |

**Response:**
```json
{
  "conversations": [
    {
      "thread_id": "sess-abc",
      "surface": "web",
      "title": "Refund policy questions",
      "turn_count": 5,
      "last_message_at": "2026-06-14T01:00:00Z",
      "created_at": "2026-06-14T00:00:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

`title` is auto-generated from the first user message (truncated to 60 chars).

---

## Get Conversation

```
GET /api/conversations/{thread_id}
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "thread_id": "sess-abc",
  "surface": "web",
  "title": "Refund policy questions",
  "turns": [
    {
      "index": 0,
      "role": "user",
      "content": "What is your refund policy?",
      "created_at": "2026-06-14T00:00:00Z"
    },
    {
      "index": 1,
      "role": "assistant",
      "content": "Our refund policy allows returns within 30 days [1].",
      "sources": [{ "title": "Refund Policy", "score": 0.92 }],
      "created_at": "2026-06-14T00:00:05Z"
    }
  ]
}
```

---

## Delete Conversation

```
DELETE /api/conversations/{thread_id}
Authorization: Bearer {jwt_token}
```

Deletes the LangGraph checkpoint rows from `langgraph.checkpoints` and the NEXUS conversation record. Irreversible.

**Response:** `204 No Content`

---

## Thread ID Format

Thread IDs follow surface-specific conventions:

| Surface | Format | Example |
|---|---|---|
| `web` | `web:{user_id}:{uuid4}` | `web:usr-abc:sess-xyz` |
| `messenger` | `msg:{sender_psid}` | `msg:psid_12345` |
| `api` | `api:{uuid4}` | `api:sess-xyz` |

Pass any string as `thread_id` to `/api/chat/stream` — NEXUS accepts arbitrary thread IDs.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Conversation belongs to different tenant |
| `404` | `thread_id` not found |

---

## Related Docs

- [POST /api/chat/stream](../chat/stream.md)
- [State Persistence](../../08-orchestrator/state-persistence.md)
