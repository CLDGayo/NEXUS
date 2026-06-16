# GET /api/dashboard/stats

Return aggregate statistics for the current workspace. Powers the admin dashboard overview cards.

---

## Request

```
GET /api/dashboard/stats
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

Optional query parameters:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `days` | integer | `7` | Lookback window for time-series data (max 90) |

---

## Response

```json
{
  "tenant_id": "uuid",
  "period_days": 7,
  "overview": {
    "total_conversations": 312,
    "total_messages": 1847,
    "unique_users": 28,
    "avg_messages_per_conversation": 5.9
  },
  "feedback": {
    "thumbs_up": 204,
    "thumbs_down": 31,
    "satisfaction_rate": 0.868
  },
  "retrieval": {
    "avg_sources_per_response": 3.2,
    "avg_rerank_score": 0.71,
    "abstention_rate": 0.034
  },
  "documents": {
    "total_active": 482,
    "total_chunks": 6214
  },
  "messages_by_day": [
    {"date": "2026-06-08", "count": 198},
    {"date": "2026-06-09", "count": 312},
    {"date": "2026-06-10", "count": 187},
    {"date": "2026-06-11", "count": 421},
    {"date": "2026-06-12", "count": 289},
    {"date": "2026-06-13", "count": 341},
    {"date": "2026-06-14", "count": 99}
  ],
  "top_topics": [
    {"topic": "pricing", "count": 87},
    {"topic": "refund policy", "count": 64},
    {"topic": "shipping", "count": 51}
  ]
}
```

### Field Reference

| Field | Source | Notes |
|---|---|---|
| `overview.total_conversations` | `app.conversations` COUNT for period | One row per thread |
| `overview.total_messages` | `app.chat_messages` COUNT for period | Includes user + assistant turns |
| `feedback.satisfaction_rate` | `thumbs_up / (thumbs_up + thumbs_down)` | Excludes unrated messages |
| `retrieval.abstention_rate` | Messages with score below `RERANK_CONFIDENCE_FLOOR` | |
| `top_topics` | Keyword extraction from recent queries | Approximate; refreshed hourly |

---

## Permissions

Requires `require_manager` (owner or admin). Members cannot view dashboard stats.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Member role |
| `422` | `days` out of range (must be 1–90) |

---

## Related Docs

- [Usage Telemetry](../workspaces/usage.md)
- [Feedback](../chat/feedback.md)
- [Observability Overview](../../13-observability/README.md)
