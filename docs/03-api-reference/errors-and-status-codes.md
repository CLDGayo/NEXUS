# Errors & Status Codes

All NEXUS API errors follow a consistent JSON envelope. This document lists every status code, its meaning in the NEXUS context, and resolution steps for the most common errors.

---

## Error Envelope

```json
{
  "detail": "Human-readable description of what went wrong"
}
```

Pydantic validation errors (422) use an extended format:

```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Status Code Reference

### 2xx — Success

| Code | Name | When returned |
|---|---|---|
| `200 OK` | Success | Read operations, updates |
| `201 Created` | Created | New resource created (workspace, invite, token) |
| `204 No Content` | No Content | Delete operations, logout |

### 4xx — Client Errors

| Code | Name | Common NEXUS causes |
|---|---|---|
| `400 Bad Request` | Bad Request | Invalid setting key, slug contains invalid characters, model not in allowlist, workspace name is empty |
| `401 Unauthorized` | Unauthorized | Missing `Authorization` header, expired JWT, invalid `nxs_` token, revoked token |
| `403 Forbidden` | Forbidden | Authenticated but wrong role (e.g., `member` calling a `require_manager` endpoint), archived workspace access |
| `404 Not Found` | Not Found | Workspace / document / product / invite / token ID does not exist |
| `409 Conflict` | Conflict | Duplicate workspace slug, duplicate member invitation, product slug already exists in tenant |
| `410 Gone` | Gone | Deprecated endpoint (`POST /api/auth/login`, `POST /api/me/password`) |
| `422 Unprocessable Entity` | Validation Error | Required field missing, wrong type, out-of-range value |
| `429 Too Many Requests` | Rate Limited | Per-route rate limit exceeded (see [Rate Limits](rate-limits.md)) |

### 5xx — Server Errors

| Code | Name | Common NEXUS causes |
|---|---|---|
| `500 Internal Server Error` | Server Error | Qdrant unreachable, Postgres connection failure, Groq API error, unhandled exception |
| `503 Service Unavailable` | Unavailable | Health check failing — Qdrant or Postgres not yet ready on startup |

---

## Common Errors & Resolutions

### 401 — Token Expired

```json
{"detail": "Could not validate credentials"}
```

**Cause:** JWT has passed its 3600-second lifetime.

**Resolution:** Call `POST /api/auth/jwt/login` to obtain a new token. Implement token refresh in your client before expiry.

---

### 401 — Invalid API Token

```json
{"detail": "Invalid or revoked API token"}
```

**Cause:** The `nxs_` token doesn't match any active record (revoked, never existed, or corrupted).

**Resolution:** Verify the full token value. If revoked, create a new token via `POST /api/tokens`.

---

### 403 — Insufficient Role

```json
{"detail": "Manager role required"}
```

or

```json
{"detail": "Owner role required"}
```

**Cause:** Your account's role in the target workspace doesn't have permission for this operation.

**Resolution:** Have the workspace owner promote your account or perform the operation themselves.

---

### 403 — Archived Workspace

```json
{"detail": "Workspace is archived"}
```

**Cause:** Attempting to use a workspace that has been archived. All operations are blocked except viewing and unarchiving.

**Resolution:** Call `POST /api/tenants/{id}/unarchive` (owner only) to restore the workspace.

---

### 409 — Slug Conflict

```json
{"detail": "A workspace with this slug already exists"}
```

**Cause:** The requested `slug` is already in use by another workspace.

**Resolution:** Choose a different slug. Slugs must be globally unique.

---

### 409 — Slug Locked (Has Documents)

```json
{"detail": "Cannot change slug: workspace has indexed documents"}
```

**Cause:** Attempting to rename a workspace slug after documents have been ingested. The slug is baked into Qdrant payload filters.

**Resolution:** Coordinate with admin to re-ingest all documents under the new slug before changing it. See [Workspace Lifecycle](../04-workspace-management/workspace-lifecycle.md).

---

### 422 — Validation Error

```json
{
  "detail": [
    {"loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error.email"}
  ]
}
```

**Cause:** Request body failed schema validation.

**Resolution:** Check the `loc` field to identify which field failed and the `msg` for the specific rule violated.

---

### 422 — Model Not Allowed

```json
{"detail": "model_choice 'gpt-5' is not in the allowed model list"}
```

**Cause:** A `PUT /api/workspace/ai-settings` request specified a `model_choice` not in the runtime allowlist.

**Resolution:** Call `GET /api/workspace/ai-settings` to see the `available_models` list in the response and choose from it.

---

### 500 — Qdrant Unavailable

```json
{"detail": "Vector store unavailable. Please try again later."}
```

**Cause:** Qdrant container not running or network unreachable.

**Resolution:**
1. `docker compose ps` — check `qdrant` container is running and healthy
2. `curl http://localhost:6333/healthz` — verify Qdrant responds
3. Check `QDRANT_URL` in `.env` matches the actual Qdrant address

---

### 500 — LLM Generation Failed

```json
{"detail": "Generation error: Rate limit exceeded on Groq"}
```

**Cause:** Groq API rate limit hit or network error.

**Resolution:**
1. Check Groq dashboard for rate limit status
2. Reduce `TOP_K` via `PATCH /api/settings` to lower token usage per request
3. Implement retry with exponential backoff in client code

---

### 410 — Deprecated Endpoint

```json
{"detail": "This endpoint has been removed. Use POST /api/auth/jwt/login instead."}
```

**Cause:** Calling a permanently removed v1 endpoint.

**Resolution:** Migrate to the replacement endpoint listed in the error message.

---

## SSE Stream Errors

The streaming chat endpoint (`POST /api/chat/stream`) delivers errors as SSE events rather than HTTP status codes (once the stream has started):

```
data: {"type": "error", "message": "Retrieval failed: Qdrant timeout"}
data: {"type": "done"}
```

If the error occurs before the stream opens (e.g., auth failure), a standard HTTP error response is returned instead.

---

## Related Docs

- [Rate Limits](rate-limits.md)
- [Authentication in the API](authentication-in-api.md)
- [Troubleshooting Index](../17-troubleshooting/README.md)
