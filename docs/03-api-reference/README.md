# API Reference

The NEXUS API is a RESTful HTTP API served by FastAPI. All endpoints return JSON. The streaming chat endpoint delivers Server-Sent Events (SSE).

---

## Base URLs

| Environment | Base URL |
|---|---|
| Production | `https://chat.nexus.gayo-sphere.cloud` |
| Local dev | `http://localhost:8501` |

All API routes are prefixed with `/api/` (v1) or `/api/v2/` (workspace management, profiles).

---

## Authentication

Every request (except `/api/health` and `/api/auth/jwt/login`) requires authentication. Two schemes are supported:

### Bearer JWT

Obtained via `POST /api/auth/jwt/login`. Valid for 3600 seconds.

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### API Token (`nxs_` prefix)

Long-lived scoped token created via `POST /api/tokens`. Useful for programmatic integrations.

```http
Authorization: Bearer nxs_abc123...
```

→ Full details: [Authentication in the API](authentication-in-api.md)

---

## Request Format

- **Content-Type:** `application/json` for all JSON body requests
- **Multipart:** `multipart/form-data` for file upload endpoints
- **Form data:** `application/x-www-form-urlencoded` for JWT login only

---

## Response Format

All successful responses return a JSON body. Errors follow a consistent envelope:

```json
{
  "detail": "Human-readable error message"
}
```

For validation errors (422):

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

## Status Codes

| Code | Meaning |
|---|---|
| `200 OK` | Request succeeded |
| `201 Created` | Resource created |
| `204 No Content` | Delete succeeded (no body) |
| `400 Bad Request` | Invalid parameters or business rule violation |
| `401 Unauthorized` | Missing or invalid authentication |
| `403 Forbidden` | Authenticated but insufficient role |
| `404 Not Found` | Resource does not exist |
| `409 Conflict` | Unique constraint violation (e.g., duplicate slug) |
| `410 Gone` | Endpoint permanently removed |
| `422 Unprocessable Entity` | Request body failed Pydantic validation |
| `429 Too Many Requests` | Rate limit exceeded |
| `500 Internal Server Error` | Unexpected server error |

→ Full error reference: [Errors & Status Codes](errors-and-status-codes.md)

---

## Versioning

| Prefix | Contents | Stability |
|---|---|---|
| `/api/` | All v1 endpoints (chat, documents, products, integrations, settings, etc.) | Stable |
| `/api/v2/` | Workspace management (tenants, profiles, admin users, health, invites) | Stable — shipped Phase 50–53 |

There is no explicit version negotiation header. Breaking changes are introduced as new routes; deprecated routes return `410 Gone` with a message.

---

## Pagination

List endpoints that may return large result sets accept:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | `int` | `50` | Maximum items to return |
| `offset` | `int` | `0` | Number of items to skip |

Responses include a `total` field alongside the item list.

---

## Endpoint Index

### Chat & Conversations
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat/stream` | [SSE streaming chat](chat/stream.md) |
| `POST` | `/api/chat/feedback` | [Submit turn feedback](chat/feedback.md) |
| `POST` | `/api/chat/upload` | [Upload chat attachment](chat/upload.md) |
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/{id}` | Get conversation |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |

### Documents
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/documents` | [List indexed documents](documents/list.md) |
| `POST` | `/api/documents/upload` | [Upload & ingest document](documents/upload.md) |
| `POST` | `/api/documents/archive` | [Archive document](documents/archive.md) |
| `POST` | `/api/documents/reconcile` | [Reconcile vault with index](documents/reconcile.md) |
| `GET` | `/api/documents/index_summary` | [Retrieval arm stats](documents/index-summary.md) |

### Workspaces (v2)
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tenants` | [Create workspace](workspaces/tenants-crud.md) |
| `GET` | `/api/tenants` | [List workspaces](workspaces/tenants-crud.md) |
| `GET` | `/api/tenants/{id}` | [Get workspace](workspaces/tenants-crud.md) |
| `PATCH` | `/api/tenants/{id}` | [Update workspace](workspaces/tenants-crud.md) |
| `GET` | `/api/tenants/{id}/members` | [List members](workspaces/members.md) |
| `PATCH` | `/api/tenants/{id}/members/{uid}` | [Update member role](workspaces/members.md) |
| `DELETE` | `/api/tenants/{id}/members/{uid}` | [Remove member](workspaces/members.md) |
| `POST` | `/api/tenants/{id}/invites` | [Create invite](workspaces/invites.md) |
| `GET` | `/api/tenants/{id}/invites` | [List invites](workspaces/invites.md) |
| `POST` | `/api/tenants/{id}/archive` | [Archive workspace](workspaces/lifecycle.md) |
| `POST` | `/api/tenants/{id}/unarchive` | [Unarchive workspace](workspaces/lifecycle.md) |
| `POST` | `/api/tenants/{id}/transfer` | [Transfer ownership](workspaces/lifecycle.md) |
| `DELETE` | `/api/tenants/{id}` | [Hard-delete workspace](workspaces/lifecycle.md) |
| `GET` | `/api/tenants/{id}/usage` | [Usage telemetry](workspaces/usage.md) |

### AI Settings
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/workspace/ai-settings` | [Get AI settings](ai-settings/ai-settings.md) |
| `PUT` | `/api/workspace/ai-settings` | [Update AI settings](ai-settings/ai-settings.md) |

### Products
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/products` | [List products](products/products.md) |
| `POST` | `/api/products` | [Create product](products/products.md) |
| `GET` | `/api/products/{id}` | [Get product](products/products.md) |
| `PATCH` | `/api/products/{id}` | [Update product](products/products.md) |
| `DELETE` | `/api/products/{id}` | [Archive product](products/products.md) |
| `POST` | `/api/products/{id}/images` | [Add image](products/products.md) |
| `PATCH` | `/api/products/{id}/images/order` | [Reorder images](products/products.md) |
| `DELETE` | `/api/products/{id}/images/{img_id}` | [Remove image](products/products.md) |

### Integrations
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/integrations` | [List integrations](integrations/integrations.md) |
| `POST` | `/api/integrations` | [Create integration](integrations/integrations.md) |
| `PATCH` | `/api/integrations/{id}` | [Update integration](integrations/integrations.md) |
| `DELETE` | `/api/integrations/{id}` | [Delete integration](integrations/integrations.md) |
| `POST` | `/api/integrations/{id}/test` | [Fire test event](integrations/integrations.md) |
| `GET` | `/api/integrations/catalog` | List available providers |
| `GET` | `/api/integrations/messenger` | Messenger config |
| `POST` | `/api/integrations/messenger/rotate-verify-token` | Rotate Messenger verify token |

### Settings & Tokens
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings` | [Get dynamic settings](settings/settings.md) |
| `PATCH` | `/api/settings` | [Update setting](settings/settings.md) |
| `POST` | `/api/settings/rotate-jwt` | Rotate JWT secret (owner only) |
| `GET` | `/api/tokens` | [List API tokens](tokens/api-tokens.md) |
| `POST` | `/api/tokens` | [Create API token](tokens/api-tokens.md) |
| `DELETE` | `/api/tokens/{id}` | [Revoke API token](tokens/api-tokens.md) |

### Dashboard, Logs & Health
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/dashboard/stats` | [KPI dashboard stats](dashboard/dashboard.md) |
| `GET` | `/api/logs` | Audit log stream |
| `GET` | `/api/changelog` | CHANGELOG entries |
| `GET` | `/api/health` | [Liveness + readiness](health/health.md) |

### Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/jwt/login` | Login — returns JWT |
| `POST` | `/api/auth/jwt/logout` | Logout |
| `POST` | `/api/auth/request-verify-token` | Request email verification |

---

## Related Docs

- [Authentication in the API](authentication-in-api.md) — JWT and API token flows
- [Errors & Status Codes](errors-and-status-codes.md) — complete error reference
- [Rate Limits](rate-limits.md) — per-route limits
- [Authentication System](../05-authentication/README.md) — deeper auth internals
