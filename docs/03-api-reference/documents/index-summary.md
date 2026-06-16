# GET /api/documents/index_summary

Returns aggregate statistics about the tenant's indexed document vault. Used by the Usage dashboard and admin tools.

---

## Request

```
GET /api/documents/index_summary
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

No query parameters.

---

## Response

```json
{
  "tenant_id": "acme-corp",
  "document_count": 148,
  "active_document_count": 143,
  "archived_document_count": 5,
  "total_chunk_count": 3241,
  "qdrant_chunk_count": 3241,
  "folders": {
    "00 - Inbox": 12,
    "01 - Projects": 45,
    "03 - Resources": 86
  },
  "top_tags": [
    { "tag": "policy", "count": 34 },
    { "tag": "onboarding", "count": 21 }
  ],
  "last_indexed_at": "2026-06-14T00:30:00Z"
}
```

| Field | Source | Notes |
|---|---|---|
| `document_count` | Postgres `app.documents` | All docs including archived |
| `active_document_count` | Postgres | `is_active=true` only |
| `total_chunk_count` | Postgres aggregate | Sum of `chunk_count` per active doc |
| `qdrant_chunk_count` | Qdrant count API | Live count; `null` if Qdrant unreachable |
| `folders` | Postgres metadata | PARA folder breakdown |
| `top_tags` | Postgres metadata | Top 10 tags by frequency |
| `last_indexed_at` | Postgres | Most recent `updated_at` across active docs |

---

## `qdrant_chunk_count` Degraded Mode

If Qdrant is unreachable, `qdrant_chunk_count` returns `null` and the response still returns `200`:

```json
{
  "qdrant_chunk_count": null,
  "qdrant_status": "unreachable"
}
```

This allows the Usage dashboard to render without hard-failing on Qdrant downtime.

---

## RBAC

All authenticated roles can access index summary.

---

## Related Docs

- [GET /api/documents](list.md)
- [POST /api/documents/reconcile](reconcile.md)
- [GET /api/tenants/{id}/usage](../workspaces/usage.md)
