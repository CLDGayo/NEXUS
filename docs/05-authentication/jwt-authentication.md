# JWT Authentication

NEXUS uses stateless JSON Web Tokens (JWTs) managed by `fastapi-users`. Tokens are signed with `NEXUS_JWT_SECRET` using HS256 and expire after 3600 seconds.

---

## Prerequisites

- `NEXUS_JWT_SECRET` set in `.env` (minimum 32 bytes)
- At least one user account created (via admin bootstrap or registration)
- API server running

---

## Login Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI /api/auth/jwt/login
    participant DB as PostgreSQL app.users

    Client->>API: POST /api/auth/jwt/login\ncontent-type: application/x-www-form-urlencoded\nusername=email&password=pass
    API->>DB: SELECT user WHERE email = ?
    DB-->>API: User row (hashed_password, is_active)
    API->>API: bcrypt verify(password, hashed_password)
    API->>API: Mint JWT {sub: user_id, aud: "fastapi-users:auth", exp: now+3600}
    API->>API: Sign with NEXUS_JWT_SECRET (HS256)
    API-->>Client: {"access_token": "eyJ...", "token_type": "bearer"}
```

---

## Step-by-Step: Obtaining a Token

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you%40example.com&password=yourpassword"
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1NTBlODQwMC1lMjliLTQxZDQtYTcxNi00NDY2NTU0NDAwMDAiLCJhdWQiOlsiZmFzdGFwaS11c2VyczphdXRoIl0sImV4cCI6MTc0OTgxNjAwMH0.abc123",
  "token_type": "bearer"
}
```

---

## Token Structure

Decoded JWT payload:

```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "aud": ["fastapi-users:auth"],
  "exp": 1749816000
}
```

| Claim | Value | Description |
|---|---|---|
| `sub` | UUID string | User ID — maps to `app.users.id` |
| `aud` | `["fastapi-users:auth"]` | Audience — must match for validation |
| `exp` | Unix timestamp | Expiry time (issued time + 3600s) |

---

## Token Properties

| Property | Value |
|---|---|
| Algorithm | HS256 (HMAC-SHA256) |
| Lifetime | 3600 seconds (1 hour) |
| Stateless | Yes — no DB lookup on validation |
| Revocable | No — only by rotating `NEXUS_JWT_SECRET` |

---

## Using a Token

Include the token in every API request:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**JavaScript example:**

```javascript
const response = await fetch('/api/documents', {
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json'
  }
});
```

---

## Token Refresh Strategy

JWTs are not refreshable — there is no refresh token endpoint. When a token expires, the client must re-authenticate via login.

**Recommended client pattern:**

```javascript
// Store token + expiry
localStorage.setItem('nexus_token', accessToken);
localStorage.setItem('nexus_token_exp', Date.now() + 3595 * 1000); // 5s buffer

// Before each request, check expiry
if (Date.now() > parseInt(localStorage.getItem('nexus_token_exp'))) {
  await relogin();
}
```

> **💡 PRO TIP:** The nexus-ui frontend handles token expiry automatically via an Axios interceptor that re-routes to the login page on 401 responses.

---

## Logout

```http
POST /api/auth/jwt/logout
Authorization: Bearer <token>
```

Returns `204 No Content`. Because JWTs are stateless, the server has no session to invalidate. The client must discard the token. The token remains technically valid until its `exp` claim passes.

---

## Rotating the JWT Secret

> **⚠️ WARNING:** Rotating the JWT secret **immediately invalidates all active sessions** for all users. Every user must re-login. This operation is irreversible.

**When to rotate:**
- A JWT token is believed to be compromised
- The `NEXUS_JWT_SECRET` environment variable was accidentally exposed
- Security policy requires periodic rotation

**How to rotate:**

```http
POST /api/settings/rotate-jwt
Authorization: Bearer <owner-jwt>
```

Response:

```json
{"message": "JWT secret rotated. All sessions invalidated. Re-login required."}
```

The new secret is stored in the environment and takes effect immediately. Update `/home/nexus-rag/.env` on the VPS to persist across restarts.

---

## Creating the First Superuser

If no users exist yet, create the initial admin account:

```bash
cd rag
uv run python -c "
import asyncio
from auth.manager import create_superuser
asyncio.run(create_superuser('admin@example.com', 'your-secure-password'))
"
```

Or via the admin API (requires an existing superuser token):

```http
POST /api/admin/users
Authorization: Bearer <superuser-jwt>
Content-Type: application/json

{
  "email": "newadmin@example.com",
  "password": "secure-password",
  "is_superuser": true
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Could not validate credentials` | Token expired or secret rotated | Re-login |
| `401` on valid-looking token | Wrong `NEXUS_JWT_SECRET` (dev/prod mismatch) | Verify env vars match between issuer and verifier |
| Login returns `400 LOGIN_BAD_CREDENTIALS` | Wrong email or password | Verify credentials; check `app.users.is_active = true` |
| Login returns `400 LOGIN_USER_NOT_VERIFIED` | Email not verified | Use `POST /api/auth/request-verify-token` |

---

## Related Docs

- [API Tokens](api-tokens.md)
- [RBAC Enforcement](rbac-enforcement.md)
- [Environment Variables — JWT](../16-configuration-reference/environment-variables.md#authentication--jwt)
- [API Reference — Authentication](../03-api-reference/authentication-in-api.md)
