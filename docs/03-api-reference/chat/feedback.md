# POST /api/chat/feedback

Submit thumbs-up / thumbs-down feedback on a chat response. Used for Langfuse score logging and future RLHF data collection.

---

## Request

```
POST /api/chat/feedback
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

```json
{
  "thread_id": "sess-abc",
  "turn_index": 2,
  "score": 1,
  "comment": "Accurate and helpful response."
}
```

| Field | Type | Required | Values | Notes |
|---|---|---|---|---|
| `thread_id` | string | Yes | — | Thread the response belongs to |
| `turn_index` | integer | Yes | ≥ 0 | 0-based turn number within thread |
| `score` | integer | Yes | `1` (up) or `-1` (down) | Thumbs signal |
| `comment` | string | No | — | Optional free-text reason |

---

## Response

```json
{ "status": "recorded" }
```

---

## What Happens Internally

1. Feedback written to `app.chat_feedback` table (thread_id, turn_index, score, comment, user_id)
2. If Langfuse is configured (`LANGFUSE_SECRET_KEY` set): score posted to the matching Langfuse generation span
3. No effect on future retrieval or generation — feedback is analytics-only at this stage

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `404` | `thread_id` not found for this tenant |
| `422` | `score` not `1` or `-1`; missing required fields |

---

## Related Docs

- [POST /api/chat/stream](stream.md)
- [Langfuse Integration](../../13-observability/langfuse.md)
