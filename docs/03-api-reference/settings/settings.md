# Settings API

Manage global dynamic settings for the NEXUS instance. These are superuser-only controls that affect all tenants (unless overridden by per-tenant AI settings).

---

## GET /api/settings

Return all current dynamic settings.

```
GET /api/settings
Authorization: Bearer {jwt_token}
```

> **📝 NOTE:** This endpoint requires superuser access (via fastapi-users), not just `require_owner`. Tenant-scoped AI overrides use `/api/workspace/ai-settings` instead.

### Response

```json
{
  "settings": [
    {"key": "TOP_K", "value": "6", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "RETRIEVE_K", "value": "50", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "CHUNK_TOKENS", "value": "400", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "CHUNK_OVERLAP", "value": "50", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "SEMANTIC_BREAK_THRESHOLD", "value": "0.55", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "RERANK_CONFIDENCE_FLOOR", "value": "0.0", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "GROQ_MODEL", "value": "llama-3.3-70b-versatile", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "FOLLOWUP_MODEL", "value": "llama-3.1-8b-instant", "updated_at": "2026-06-01T10:00:00Z"},
    {"key": "THEME", "value": "dark", "updated_at": "2026-06-01T10:00:00Z"}
  ]
}
```

---

## PATCH /api/settings

Update one or more settings.

```
PATCH /api/settings
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{
  "TOP_K": "8",
  "GROQ_MODEL": "llama-3.1-8b-instant"
}
```

All values are stored as strings. Numeric keys are parsed at read time. Unknown keys are rejected with `422`.

### Valid SETTING_KEYS

| Key | Type | Effect |
|---|---|---|
| `TOP_K` | int | Reranked results returned to LLM (default: 6) |
| `RETRIEVE_K` | int | Candidates fetched per retrieval arm (default: 50) |
| `CHUNK_TOKENS` | int | Target chunk size in tokens (default: 400) |
| `CHUNK_OVERLAP` | int | Token overlap between adjacent chunks (default: 50) |
| `SEMANTIC_BREAK_THRESHOLD` | float | Cosine distance threshold for semantic boundaries (default: 0.55) |
| `RERANK_CONFIDENCE_FLOOR` | float | Minimum reranker score; below → abstain (default: 0.0) |
| `GROQ_MODEL` | string | Primary LLM model ID |
| `FOLLOWUP_MODEL` | string | Follow-up suggestion model ID |
| `THEME` | string | UI theme: `"dark"` or `"light"` |

---

## POST /api/settings/rotate-jwt

Rotate the `JWT_SECRET` used to sign all bearer tokens. All existing sessions are immediately invalidated.

```
POST /api/settings/rotate-jwt
Authorization: Bearer {jwt_token}
```

> **🔒 SECURITY:** This endpoint requires `require_owner` AND superuser. It is the most destructive auth operation available — all active user sessions across all tenants are terminated when the secret rotates.

```json
{
  "status": "rotated",
  "invalidated_sessions": "all",
  "note": "All existing JWT tokens are now invalid. Users must log in again."
}
```

---

## Related Docs

- [Dynamic Settings Reference](../../16-configuration-reference/dynamic-settings.md)
- [Environment Variables](../../16-configuration-reference/environment-variables.md)
- [AI Settings (per-tenant)](../ai-settings/ai-settings.md)
