# Usage Telemetry

The usage endpoint provides a real-time snapshot of resource consumption for a workspace — document counts, member counts, Qdrant vector chunks, and a 7-day message activity trend.

---

## Endpoint

```http
GET /api/tenants/{tenant_id}/usage
Authorization: Bearer <manager-jwt>
```

**Required role:** `admin` or `owner` (`require_manager`)

---

## Response Structure

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_name": "Acme Corp",
  "slug": "acme-corp",
  "documents": {
    "total": 342,
    "archived": 12,
    "active": 330
  },
  "products": {
    "total": 47,
    "active": 45
  },
  "members": {
    "total": 8,
    "by_role": {
      "owner": 1,
      "admin": 2,
      "member": 5
    }
  },
  "vectors": {
    "chunk_count": 4821,
    "status": "ok"
  },
  "messages": {
    "last_7_days": [
      {"date": "2026-06-07", "count": 142},
      {"date": "2026-06-08", "count": 198},
      {"date": "2026-06-09", "count": 87},
      {"date": "2026-06-10", "count": 204},
      {"date": "2026-06-11", "count": 312},
      {"date": "2026-06-12", "count": 189},
      {"date": "2026-06-13", "count": 94}
    ],
    "total_last_7_days": 1226
  },
  "computed_at": "2026-06-13T12:00:00Z"
}
```

---

## Field Reference

### `documents`

| Field | Source | Description |
|---|---|---|
| `total` | `COUNT(*) FROM app.documents WHERE tenant_id = ?` | All document rows for this workspace |
| `archived` | `COUNT(*) WHERE archived_at IS NOT NULL` | Soft-deleted documents |
| `active` | `total - archived` | Queryable documents |

### `products`

| Field | Source | Description |
|---|---|---|
| `total` | `COUNT(*) FROM app.products WHERE tenant_id = ?` | All product rows |
| `active` | `COUNT(*) WHERE is_active = true` | Live, queryable products |

### `members`

Counts from `app.tenant_users` grouped by role. Includes pending invitees only after they accept.

### `vectors`

| Field | Description |
|---|---|
| `chunk_count` | Number of Qdrant points with `tenant_id = slug` (live query to Qdrant) |
| `status` | `"ok"` if Qdrant responded, `"unavailable"` if Qdrant unreachable (graceful null degrade) |

> **📝 NOTE:** The Qdrant chunk count is fetched live on each request using the `scroll` + `count` API. On very large vaults (>100k chunks), this query may add 100–300ms latency. If Qdrant is unreachable, `vectors.chunk_count` returns `null` and `vectors.status` returns `"unavailable"` — the rest of the response is still returned.

### `messages`

7-day message volume buckets from `app.messages WHERE tenant_id = ? AND created_at >= now() - 7 days`, grouped by date in the workspace's timezone.

---

## UI: Usage Dashboard Tab

The nexus-ui frontend displays this data in the **Usage** tab of Workspace Settings (`/settings/workspaces/:slug`):

- Document and product counts as metric cards
- Member breakdown as a role distribution badge
- 7-day message trend as a bar chart (recharts)
- Vector chunk count as a technical detail card

---

## Polling Behavior

The UI does not auto-poll the usage endpoint. Data is fetched once on tab open. Refresh the page to get updated counts.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `vectors.chunk_count` is `null` | Qdrant unreachable | Check Qdrant container health; `curl http://qdrant:6333/healthz` |
| Document count doesn't match Qdrant count | Ingest partially completed or documents deleted without re-index | Run `POST /api/documents/reconcile` to re-sync |
| Message counts show 0 for recent days | Timezone offset | Verify server timezone and `created_at` timestamps in `app.messages` |

---

## Related Docs

- [Workspace Lifecycle](workspace-lifecycle.md)
- [GET /api/tenants/{id}/usage](../03-api-reference/workspaces/usage.md)
- [Observability — Health Endpoint](../13-observability/health-endpoint.md)
