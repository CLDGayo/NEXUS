# POST /api/documents/archive

Soft-delete a document. Archived documents are removed from retrieval but their vectors remain in Qdrant with `is_active: false` payload.

---

## Request

```
POST /api/documents/archive
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{ "document_id": "uuid" }
```

Or archive by filename:

```json
{ "filename": "old-policy.md" }
```

Provide exactly one of `document_id` or `filename`.

---

## Response

```json
{
  "document_id": "uuid",
  "filename": "old-policy.md",
  "status": "archived",
  "chunk_count": 14
}
```

---

## What Happens Internally

1. `app.documents.is_active` set to `false`
2. All Qdrant points for this document updated: payload `is_active → false`
3. Retrieval queries filter `is_active: true` — archived chunks excluded immediately
4. MinIO file **not** deleted (recoverable by re-upload or manual unarchive)

---

## Unarchive

No dedicated unarchive endpoint currently. To restore:

1. Re-upload the same file via `POST /api/documents/upload`
2. Old archived record remains; new record created with fresh chunks

---

## RBAC

| Action | Required role |
|---|---|
| Archive | `admin` or `owner` |

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | `member` role |
| `404` | Document not found |
| `409` | Document already archived |

---

## Related Docs

- [GET /api/documents](list.md)
- [POST /api/documents/reconcile](reconcile.md)
