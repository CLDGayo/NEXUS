# Authentication in the API

NEXUS supports two authentication schemes. Both are carried as `Authorization: Bearer <token>` headers and are accepted on all protected endpoints.

---

## Scheme 1 — Bearer JWT

### Obtaining a Token

```http
POST /api/auth/jwt/login
Content-Type: application/x-www-form-urlencoded

username=admin%40example.com&password=your-password
```

Response:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### Using the Token

```http
GET /api/documents
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Token Properties

| Property | Value |
|---|---|
| Algorithm | HS256 |
| Lifetime | 3600 seconds (1 hour) |
| Secret | `NEXUS_JWT_SECRET` env var |
| Audience | `fastapi-users:auth` |
| Stateless | Yes — no DB lookup on validation |

> **⚠️ WARNING:** JWT tokens cannot be revoked before expiry. If a token is leaked, rotate the JWT secret via `POST /api/settings/rotate-jwt` (owner only). This invalidates **all** existing tokens immediately.

### Logout

```http
POST /api/auth/jwt/logout
Authorization: Bearer <token>
```

Returns `204 No Content`. Because JWTs are stateless, logout is a client-side concern — the token remains technically valid until expiry, but the client should discard it.

---

## Scheme 2 — API Tokens (`nxs_` prefix)

API tokens are long-lived, scoped tokens for programmatic access. They never expire unless explicitly revoked.

### Creating a Token

Requires a valid JWT (admin operation):

```http
POST /api/tokens
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "My Integration",
  "scopes": ["chat:read", "chat:write"]
}
```

Response (token value shown **once only** — store it securely):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Integration",
  "token": "nxs_abc123def456...",
  "prefix": "nxs_abc1",
  "scopes": ["chat:read", "chat:write"],
  "created_at": "2026-06-13T00:00:00Z"
}
```

> **⚠️ WARNING:** The full token value is only returned in this response. NEXUS stores only the SHA-256 hash. If you lose the token, revoke it and create a new one.

### Using an API Token

```http
POST /api/chat/stream
Authorization: Bearer nxs_abc123def456...
Content-Type: application/json

{"message": "What is NEXUS?", "session_id": "integration-session-1"}
```

### Available Scopes

| Scope | Permitted operations |
|---|---|
| `chat:read` | Read conversation history, retrieve sessions |
| `chat:write` | Send messages, upload attachments |
| `documents:read` | List documents, read index summary |
| `documents:write` | Upload, archive, reconcile documents |
| `dashboard:read` | Read dashboard stats and KPIs |

> **📝 NOTE:** A JWT (login token) implicitly has all scopes. API tokens are restricted to the scopes specified at creation time.

### Revoking a Token

```http
DELETE /api/tokens/{token_id}
Authorization: Bearer <jwt>
```

Returns `204 No Content`. The token is immediately invalid for all future requests.

---

## Role-Based Access Control

Authentication establishes identity. Authorization is determined by the user's **role** within a workspace:

```mermaid
graph TD
    REQ["Incoming Request"] --> AUTH["require_auth()\nValidate JWT or nxs_ token"]
    AUTH -->|invalid| 401["401 Unauthorized"]
    AUTH -->|valid| ROLE{"Check role\nfor endpoint"}
    ROLE -->|member endpoint| OK["200 OK"]
    ROLE -->|manager endpoint| MGMT{"require_manager()\nrole in owner, admin"}
    MGMT -->|owner or admin| OK
    MGMT -->|member| 403["403 Forbidden"]
    ROLE -->|owner endpoint| OWN{"require_owner()\nrole == owner"}
    OWN -->|owner| OK
    OWN -->|admin or member| 403
```

| Dependency | Required role | Used on |
|---|---|---|
| `require_auth()` | Any authenticated user | Read-only + admin endpoints |
| `require_manager()` | `owner` or `admin` | Member management, settings, invites |
| `require_owner()` | `owner` only | Archive, ownership transfer, hard-delete, JWT rotation |
| `require_auth_or_token(scope)` | JWT **or** valid scoped API token | Chat, documents, dashboard |

---

## Token Identification Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI deps.py
    participant DB as PostgreSQL

    Client->>API: Authorization: Bearer <value>
    API->>API: Does value start with "nxs_"?
    alt API Token
        API->>API: Compute SHA-256 hash
        API->>DB: SELECT * FROM app.api_tokens WHERE token_hash = ?
        DB-->>API: Token row (or 401 if not found)
        API->>API: Check revoked_at IS NULL
        API->>API: Check required scope in scopes_csv
        API->>DB: UPDATE last_used_at = now()
        API-->>Client: Proceed with token.user_id
    else JWT
        API->>API: Verify HS256 signature with NEXUS_JWT_SECRET
        API->>API: Check exp claim (3600s lifetime)
        API-->>Client: Proceed with jwt.sub (user_id)
    end
```

---

## Public Endpoints (No Auth Required)

| Path | Purpose |
|---|---|
| `GET /api/health` | Liveness and readiness probe |
| `POST /api/auth/jwt/login` | Obtain JWT token |
| `POST /api/auth/request-verify-token` | Email verification |
| `GET /join` | Workspace invite acceptance (validates invite token, no JWT needed) |
| `GET /` | SPA entry point |

---

## Related Docs

- [API Tokens — Full Reference](../05-authentication/api-tokens.md)
- [JWT Authentication — Internals](../05-authentication/jwt-authentication.md)
- [RBAC Enforcement](../05-authentication/rbac-enforcement.md)
- [POST /api/tokens](../03-api-reference/tokens/api-tokens.md)
