# Workspace Lifecycle

Advanced workspace operations: slug change, avatar upload, archive, ownership transfer, and hard-delete.

---

## Update Slug

```
PATCH /api/tenants/{id}/slug
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{ "slug": "acme-corporation" }
```

**Constraint:** Blocked if `document_count > 0`. Qdrant payload key and MinIO paths use the slug — changing it after documents are indexed requires a full re-index.

**RBAC:** `owner`

---

## Upload Avatar

```
POST /api/tenants/{id}/avatar
Authorization: Bearer {jwt_token}
Content-Type: multipart/form-data
```

```bash
curl -X POST .../api/tenants/{id}/avatar \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@logo.webp"
```

- Format: WebP (converted server-side)
- Max size: 2MB
- Stored at `tenants/{slug}/avatar.webp` in MinIO
- `avatar_url` in tenant object updated to new presigned URL

**RBAC:** `admin` or `owner`

---

## Archive Workspace

```
POST /api/tenants/{id}/archive
Authorization: Bearer {jwt_token}
```

Sets `archived_at = now()`. Once archived:
- All mutations return `423 Locked` (except `GET /api/tenants` — see note below)
- Members can still view the workspace but cannot modify it
- Documents remain in Qdrant and Postgres
- Chat queries blocked with `403`

> `GET /api/tenants` is explicitly exempt from the archived-workspace guard so users can switch to another active workspace.

**RBAC:** `owner`

**Response:** `200` with updated tenant object including `archived_at`.

---

## Unarchive Workspace

```
POST /api/tenants/{id}/unarchive
Authorization: Bearer {jwt_token}
```

Sets `archived_at = null`. All operations resume normally.

**RBAC:** `owner`

---

## Transfer Ownership

```
POST /api/tenants/{id}/transfer-owner
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{ "new_owner_user_id": "uuid" }
```

- `new_owner_user_id` must be an existing member
- Current owner is downgraded to `admin`
- New owner is upgraded to `owner`
- Atomic — both role changes in single transaction

**RBAC:** `owner`

---

## Hard Delete

```
DELETE /api/tenants/{id}
Authorization: Bearer {jwt_token}
```

Permanently and irreversibly destroys the workspace. Cascade order:

```
1. Qdrant: delete all points where payload.tenant_id = slug (slug-filter delete)
2. Postgres: DELETE FROM app.tenants WHERE id = {id}
   → FK cascade: tenant_members, documents, products, integrations, conversations, invites
3. MinIO: async cleanup of tenants/{slug}/ prefix (best-effort)
```

> **WARNING:** If Qdrant is unreachable at delete time, the request aborts with `503`. The workspace is NOT deleted. This prevents orphaned vectors.
>
> If Qdrant succeeds but Postgres fails (rare), vectors are orphaned. Run `POST /api/documents/reconcile` after recovery.

**Confirmation required:** Request body must include:
```json
{ "confirm": "DELETE acme-corp" }
```

Where `"acme-corp"` is the tenant slug. Request rejected if string does not match exactly.

**RBAC:** `owner`

**Response:** `204 No Content`

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `403` | Insufficient role |
| `409` | Slug change blocked — documents exist |
| `423` | Workspace archived — mutation blocked |
| `503` | Qdrant unreachable during hard delete |

---

## Related Docs

- [Danger Zone Guide](../../04-workspace-management/danger-zone.md)
- [Workspace Lifecycle Guide](../../04-workspace-management/workspace-lifecycle.md)
- [Avatar & Branding](../../04-workspace-management/avatar-branding.md)
