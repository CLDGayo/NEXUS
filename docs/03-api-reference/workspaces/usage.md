# GET /api/tenants/{id}/usage

Returns usage telemetry for a workspace. Powers the Usage tab in workspace settings.

---

## Request

```
GET /api/tenants/{id}/usage
Authorization: Bearer {jwt_token}
```

No query parameters.

---

## Response

```json
{
  "tenant_id": "acme-corp",
  "document_count": 148,
  "product_count": 12,
  "member_count": 5,
  "chunk_count": 3241,
  "message_buckets": [
    { "date": "2026-06-08", "count": 34 },
    { "date": "2026-06-09", "count": 41 },
    { "date": "2026-06-10", "count": 28 },
    { "date": "2026-06-11", "count": 55 },
    { "date": "2026-06-12", "count": 62 },
    { "date": "2026-06-13", "count": 48 },
    { "date": "2026-06-14", "count": 19 }
  ]
}
```

| Field | Source | Notes |
|---|---|---|
| `document_count` | Postgres `app.documents` | Active only |
| `product_count` | Postgres `app.products` | Active only |
| `member_count` | Postgres `app.tenant_members` | All roles |
| `chunk_count` | Qdrant count API | `null` if Qdrant unreachable (graceful degrade) |
| `message_buckets` | Postgres `app.chat_turns` | Last 7 days, grouped by UTC date |

---

## Degraded Mode

If Qdrant is unreachable:

```json
{
  "chunk_count": null,
  "qdrant_status": "unreachable"
}
```

All other fields return normally — Qdrant unavailability does not fail the endpoint.

---

## RBAC

All authenticated members can view usage data.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `404` | Tenant not found or user not a member |

---

## Related Docs

- [Usage Telemetry Guide](../../04-workspace-management/usage-telemetry.md)
- [GET /api/documents/index_summary](../documents/index-summary.md)
- [Workspace Settings UI](../../09-frontend/workspace-settings-ui.md)
