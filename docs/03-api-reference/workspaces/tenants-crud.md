# Tenants CRUD

Core workspace management endpoints. A "tenant" and "workspace" are interchangeable terms — `app.tenants` is the backing table.

---

## List Tenants

```
GET /api/tenants
Authorization: Bearer {jwt_token}
```

Returns all tenants the authenticated user is a member of.

**Response:**
```json
{
  "tenants": [
    {
      "id": "uuid",
      "slug": "acme-corp",
      "name": "Acme Corp",
      "avatar_url": "https://...",
      "role": "owner",
      "is_active": true,
      "created_at": "2026-06-01T00:00:00Z"
    }
  ]
}
```

> This endpoint is **exempt from the archived-workspace guard** — it must return even when the current workspace is archived so users can switch workspaces.

---

## Create Tenant

```
POST /api/tenants
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{
  "name": "Acme Corp",
  "slug": "acme-corp"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Display name, 2–80 chars |
| `slug` | string | No | Auto-generated from name if omitted; URL-safe, unique globally |

**Response:** `201 Created` with full tenant object. Creator is automatically assigned `owner` role.

---

## Get Tenant

```
GET /api/tenants/{id}
Authorization: Bearer {jwt_token}
```

Returns full tenant object including `avatar_url`, `archived_at`, member count.

---

## Update Tenant

```
PATCH /api/tenants/{id}
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{ "name": "Acme Corporation" }
```

**Updatable fields:** `name` only via PATCH. Slug changes and avatar updates use dedicated endpoints.

**RBAC:** `admin` or `owner`

---

## Slug Rules

- Globally unique (across all tenants)
- Immutable after creation if documents exist: `PATCH /api/tenants/{id}/slug` returns `409` when `document_count > 0`
- Format: lowercase alphanumeric + hyphens, 3–60 chars
- Used as Qdrant payload filter key and MinIO path prefix

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Insufficient role for mutation |
| `404` | Tenant not found or user not a member |
| `409` | Slug already taken |
| `423` | Workspace archived — mutations blocked (except `GET /api/tenants`) |

---

## Related Docs

- [Members](members.md)
- [Lifecycle](lifecycle.md)
- [RBAC Model](../../04-workspace-management/rbac-model.md)
