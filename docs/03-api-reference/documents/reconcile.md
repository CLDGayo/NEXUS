# POST /api/documents/reconcile

Reconcile the Postgres document index against the Qdrant vector store. Identifies and repairs drift: documents in Postgres with no vectors, or vectors with no Postgres record.

---

## Request

```
POST /api/documents/reconcile
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{
  "dry_run": true,
  "fix": false
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `dry_run` | bool | `true` | Report drift without making changes |
| `fix` | bool | `false` | When `true`, re-index missing vectors and purge orphans |

---

## Response (dry_run)

```json
{
  "tenant_id": "acme-corp",
  "postgres_count": 148,
  "qdrant_count": 3241,
  "missing_vectors": [
    { "document_id": "uuid", "filename": "report.md", "chunk_count": 12 }
  ],
  "orphan_vectors": [
    { "point_id": "uuid", "filename": "deleted.md" }
  ],
  "drift_score": 2
}
```

| Field | Notes |
|---|---|
| `missing_vectors` | Documents in Postgres with no matching Qdrant points |
| `orphan_vectors` | Qdrant points with no matching Postgres document record |
| `drift_score` | Total count of inconsistent items |

---

## Response (fix: true)

```json
{
  "fixed": {
    "re_indexed": 1,
    "orphans_purged": 1
  },
  "drift_score_after": 0
}
```

---

## When to Run

- After Qdrant restart or data volume failure
- After bulk document imports via watcher/CLI
- After failed upload (partial chunk write)
- As part of periodic maintenance (weekly cron)

---

## RBAC

| Action | Required role |
|---|---|
| Reconcile | `owner` only |

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Not `owner` |
| `503` | Qdrant unreachable during reconcile |

---

## Related Docs

- [GET /api/documents/index_summary](index-summary.md)
- [Stage 1 — Ingestion](../../02-rag-pipeline/stage-1-ingestion.md)
- [Deployment Issues](../../17-troubleshooting/deployment-issues.md)
