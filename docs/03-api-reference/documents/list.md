# GET /api/documents

List documents indexed in the tenant's vault.

---

## Request

```
GET /api/documents
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

**Query parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `limit` | integer | 50 | Max 200 |
| `offset` | integer | 0 | Pagination offset |
| `folder` | string | — | Filter by PARA folder path |
| `tags` | string | — | Comma-separated; returns docs matching ANY tag |
| `is_active` | bool | `true` | `false` returns archived only |
| `search` | string | — | Fuzzy filename search (Postgres `ILIKE`) |

---

## Response

```json
{
  "documents": [
    {
      "id": "uuid",
      "filename": "knowledge-base.md",
      "folder": "03 - Resources",
      "tags": ["policy", "onboarding"],
      "chunk_count": 22,
      "is_active": true,
      "content_hash": "sha256:abc123...",
      "created_at": "2026-06-14T00:00:00Z",
      "updated_at": "2026-06-14T00:00:00Z"
    }
  ],
  "total": 148,
  "limit": 50,
  "offset": 0
}
```

---

## Get Single Document

```
GET /api/documents/{id}
Authorization: Bearer {jwt_token}
```

Returns same fields as list item, plus `source_url` (presigned MinIO URL valid 1h).

---

## RBAC

All authenticated users (`member`, `admin`, `owner`) can list and view documents.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `404` | Document not found or belongs to different tenant |

---

## Related Docs

- [POST /api/documents/upload](upload.md)
- [POST /api/documents/archive](archive.md)
- [GET /api/documents/index_summary](index-summary.md)
