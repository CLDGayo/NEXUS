# POST /api/documents/upload

Upload a document to the tenant's vault for permanent indexing into Qdrant.

---

## Request

```
POST /api/documents/upload
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: multipart/form-data
```

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@knowledge-base.md" \
  -F "folder=03 - Resources" \
  -F "tags=policy,onboarding"
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | Yes | PDF, MD, TXT |
| `folder` | string | No | PARA folder path for metadata |
| `tags` | string | No | Comma-separated tags |

---

## Supported Formats

| Format | Max size | Notes |
|---|---|---|
| `.md` | 10MB | Heading-path metadata extracted |
| `.pdf` | 20MB | Text via `pypdf` + `pymupdf`; no OCR |
| `.txt` | 5MB | Plain text |

---

## Response

```json
{
  "document_id": "uuid",
  "filename": "knowledge-base.md",
  "chunk_count": 22,
  "status": "indexed",
  "content_hash": "sha256:abc123..."
}
```

`content_hash` is stored per chunk. Re-uploading the same file produces the same hashes — Qdrant upsert is idempotent.

---

## What Happens Internally

1. File stored to MinIO under `tenants/{slug}/documents/{document_id}/`
2. Text extracted and chunked via `ingest_v2/` pipeline (heading-walk, 400-token chunks, 50-token overlap)
3. Frontmatter parsed → chunk metadata (title, tags, folder, wikilinks)
4. Chunks embedded via fastembed `BAAI/bge-small-en-v1.5`
5. Upserted to Qdrant collection `nexus-vault` with `tenant_id` payload
6. Record written to `app.documents`

---

## RBAC

| Action | Required role |
|---|---|
| Upload | `admin` or `owner` |

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | `member` role — lacks upload permission |
| `413` | File exceeds size limit |
| `415` | Unsupported format |
| `503` | MinIO or Qdrant unreachable |

---

## Related Docs

- [Stage 1 — Ingestion](../../02-rag-pipeline/stage-1-ingestion.md)
- [Stage 2 — Metadata](../../02-rag-pipeline/stage-2-metadata-extraction.md)
- [GET /api/documents](list.md)
- [GET /api/documents/index_summary](index-summary.md)
