# API Tokens

API tokens (`nxs_` prefix) are long-lived, scoped credentials for programmatic access. They complement JWTs for integrations, scripts, and services that can't perform interactive login.

---

## Prerequisites

- An active JWT (login token) from `POST /api/auth/jwt/login`
- Target workspace and desired scopes identified

---

## Token Anatomy

```
nxs_7a3f9c2e1b4d8a6f5e3c2b1a9d7f4e2c8b6a5d3f1e9c7b4a2d8f6e3c1b9a7
│────────────────────────────────────────────────────────────────────
│ prefix (4 chars used as display prefix in the UI)
```

| Component | Description |
|---|---|
| `nxs_` prefix | Identifies this as a NEXUS API token (not a JWT) |
| Remaining bytes | Cryptographically random — never predictable |

**Storage:** Only the SHA-256 hash is stored in `app.api_tokens.token_hash`. The plaintext value is shown **once** at creation time.

---

## Available Scopes

| Scope | Permitted operations |
|---|---|
| `chat:read` | `GET /api/conversations`, read session history |
| `chat:write` | `POST /api/chat/stream`, upload attachments |
| `documents:read` | `GET /api/documents`, `GET /api/documents/index_summary` |
| `documents:write` | `POST /api/documents/upload`, archive, reconcile |
| `dashboard:read` | `GET /api/dashboard/stats`, read KPIs |

> **📝 NOTE:** A JWT carries full access equivalent to all scopes. API tokens are limited to the scopes specified at creation — you cannot expand scopes later; create a new token.

---

## Creating a Token

```http
POST /api/tokens
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "n8n Integration",
  "scopes": ["chat:read", "chat:write"]
}
```

**Response (token shown once — store immediately):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "n8n Integration",
  "token": "nxs_7a3f9c2e1b4d8a6f5e3c2b1a9d7f4e2c8b6a5d3f1e9c7b4a2d8f6e3c1b9a7",
  "prefix": "nxs_7a3f",
  "scopes": ["chat:read", "chat:write"],
  "created_at": "2026-06-13T00:00:00Z",
  "last_used_at": null
}
```

> **⚠️ WARNING:** Store the `token` value immediately. It is not retrievable after this response. If lost, revoke and create a new token.

---

## Using a Token

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/chat/stream \
  -H "Authorization: Bearer nxs_7a3f9c2e1b4d8a6f..." \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the key features?", "session_id": "integration-001"}'
```

**Scope enforcement:** If the token lacks the required scope, the server returns:

```json
{"detail": "Insufficient token scope. Required: documents:write"}
```

---

## Listing Tokens

```http
GET /api/tokens
Authorization: Bearer <jwt>
```

Response shows all tokens for the current user. The plaintext token value is **never** included — only `id`, `name`, `prefix`, `scopes`, `created_at`, `last_used_at`, and `revoked_at`.

```json
[
  {
    "id": "550e8400-...",
    "name": "n8n Integration",
    "prefix": "nxs_7a3f",
    "scopes": ["chat:read", "chat:write"],
    "created_at": "2026-06-13T00:00:00Z",
    "last_used_at": "2026-06-13T06:30:00Z",
    "revoked_at": null
  }
]
```

---

## Revoking a Token

```http
DELETE /api/tokens/{token_id}
Authorization: Bearer <jwt>
```

Returns `204 No Content`. Revocation is immediate — the token is invalid for all subsequent requests. The row in `app.api_tokens` is not deleted; `revoked_at` is set to the current timestamp.

---

## Token Validation Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI deps.py
    participant DB as PostgreSQL app.api_tokens

    Client->>API: Authorization: Bearer nxs_abc123...
    API->>API: Detect nxs_ prefix
    API->>API: Compute SHA-256(nxs_abc123...)
    API->>DB: SELECT * FROM app.api_tokens\nWHERE token_hash = ?
    DB-->>API: Token row
    API->>API: Check revoked_at IS NULL
    API->>API: Check required scope in scopes_csv
    API->>DB: UPDATE last_used_at = now()
    API-->>Client: Proceed with token.user_id
```

---

## Security Best Practices

- **Minimum scopes:** Only request the scopes your integration needs.
- **One token per integration:** Separate tokens per service makes revocation surgical.
- **Never log tokens:** Ensure your integration code doesn't write the `nxs_` value to logs.
- **Rotate periodically:** Revoke and recreate tokens for long-running integrations every 90 days.
- **Environment variables:** Store tokens in env vars or secret managers — never hardcode in source.

```bash
# Good: token from environment variable
export NEXUS_API_TOKEN="nxs_7a3f..."
curl -H "Authorization: Bearer $NEXUS_API_TOKEN" ...

# Bad: hardcoded
curl -H "Authorization: Bearer nxs_7a3f..." ...
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Invalid or revoked API token` | Token revoked or hash mismatch | Verify full token value; create new token if revoked |
| `403 Insufficient token scope` | Token lacks required scope | Create new token with the required scope |
| Token works once then fails | Token hash corrupted in transit | Ensure no URL encoding of the `nxs_` value |
| Can't find token after creation | Token value not saved | Revoke and create new — plaintext is shown once only |

---

## Related Docs

- [JWT Authentication](jwt-authentication.md)
- [RBAC Enforcement](rbac-enforcement.md)
- [POST /api/tokens](../03-api-reference/tokens/api-tokens.md)
