# POST /api/chat/upload

Upload a file to attach to a chat session. Uploaded files are chunked and temporarily indexed for retrieval within the current thread.

---

## Request

```
POST /api/chat/upload
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: multipart/form-data
```

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/chat/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf" \
  -F "thread_id=sess-abc"
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | Yes | PDF, MD, TXT supported |
| `thread_id` | string | No | Associate upload with existing thread |

---

## Supported Formats

| Format | Max size | Processing |
|---|---|---|
| `.pdf` | 20MB | Text extracted via `pypdf` + `pymupdf` |
| `.md` | 5MB | Parsed as Markdown with heading-path metadata |
| `.txt` | 5MB | Plain text chunked at sentence boundaries |

---

## Response

```json
{
  "upload_id": "uuid",
  "filename": "report.pdf",
  "chunk_count": 14,
  "thread_id": "sess-abc",
  "expires_at": "2026-06-15T01:00:00Z"
}
```

| Field | Notes |
|---|---|
| `upload_id` | Reference ID; not currently needed in subsequent requests |
| `chunk_count` | Number of chunks indexed into session-scoped Qdrant namespace |
| `expires_at` | Chunks purged after 24h; re-upload if needed across sessions |

---

## How It Works

1. File uploaded to MinIO under `uploads/{tenant_id}/{thread_id}/{upload_id}/`
2. Text extracted and chunked (same pipeline as `ingest_v2/`)
3. Chunks upserted to Qdrant with payload `{"source_kind": "upload", "thread_id": thread_id, "upload_id": upload_id}`
4. Subsequent `/api/chat/stream` calls with same `thread_id` include upload chunks in retrieval

---

## Limitations

- Upload chunks are **session-scoped** — they do not persist in the tenant's permanent vault
- Maximum 5 files per thread
- File content is not shown to the user — it is retrieved like any vault document

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `413` | File exceeds size limit |
| `415` | Unsupported file format |
| `422` | `file` field missing |
| `503` | MinIO or Qdrant unreachable during processing |

---

## Related Docs

- [POST /api/chat/stream](stream.md)
- [Stage 1 — Ingestion](../../02-rag-pipeline/stage-1-ingestion.md)
- [Chat Interface — File Uploads](../../09-frontend/chat-interface.md)
