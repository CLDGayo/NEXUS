# Creating Workspaces

Every user starts with a personal workspace auto-provisioned at signup. Additional workspaces can be created via the API or UI for team environments.

---

## Auto-Provisioning on Signup

When a new user registers, `rag/auth/manager.py::_provision_personal_tenant()` automatically creates a workspace:

- **Name:** Derived from the user's email local part (e.g., `john@example.com` → `John`)
- **Slug:** Slugified from the name (e.g., `john`), with a numeric suffix if already taken (`john-2`)
- **Role:** The registering user becomes `owner`

No action required — every user has a workspace immediately after signup.

---

## Creating Additional Workspaces

```http
POST /api/tenants
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "name": "Acme Corp",
  "slug": "acme-corp"
}
```

The `slug` field is optional. If omitted, NEXUS derives it from `name` using `slugify_tenant_name()`.

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Acme Corp",
  "slug": "acme-corp",
  "avatar_url": null,
  "archived_at": null,
  "created_at": "2026-06-13T00:00:00Z",
  "my_role": "owner"
}
```

The calling user is automatically assigned the `owner` role.

---

## Slug Rules

The slug is the workspace's permanent identifier. It is used as the `tenant_id` in Qdrant's payload filter and in API paths.

| Rule | Detail |
|---|---|
| Unique | Must be globally unique across all workspaces |
| URL-safe | Lowercase letters, numbers, hyphens only |
| Non-empty | Must not be blank or whitespace-only |
| Immutable once documents exist | Cannot be renamed after documents are ingested (Qdrant constraint) |

**Slug derivation from name:**

```python
import re
slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
# "Acme Corp!" → "acme-corp"
# "My Company 2" → "my-company-2"
```

**Collision handling:** If the derived slug is taken, a numeric suffix is appended (`acme-corp-2`, `acme-corp-3`, …).

> **💡 PRO TIP:** Set an explicit `slug` at creation time if you need a clean, predictable identifier for API integrations. Avoid relying on auto-derived slugs for external systems.

---

## Listing Your Workspaces

```http
GET /api/tenants
Authorization: Bearer <jwt>
```

Returns all workspaces the authenticated user is a member of, including their role in each:

```json
[
  {
    "id": "...",
    "name": "Personal",
    "slug": "john",
    "my_role": "owner",
    "member_count": 1,
    "archived_at": null
  },
  {
    "id": "...",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "my_role": "admin",
    "member_count": 8,
    "archived_at": null
  }
]
```

---

## Switching Workspaces in the UI

The nexus-ui frontend shows a **workspace switcher** in the sidebar. Clicking a workspace sets it as the active context for all subsequent operations (chat, documents, products, settings).

Workspace context is stored in the `TenantProvider` React context and persisted in `localStorage` as `nexus_active_tenant_slug`.

---

## Workspace Isolation Guarantee

After creation, the new workspace is fully isolated:

- **Qdrant:** All queries filter on `tenant_id = slug` — no documents from other workspaces are ever returned
- **PostgreSQL:** All tables with `tenant_id` FK only return rows matching the active workspace
- **MinIO:** Objects stored under `{bucket}/{slug}/` path prefix

No data from the auto-provisioned personal workspace bleeds into new workspaces.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `409 Conflict` on creation | Slug already in use | Choose a different name/slug |
| Workspace not visible in list | User not a member | Verify membership via `GET /api/tenants/{id}/members` |
| Can't ingest to new workspace | Slug not set up in ingest command | Pass `--tenant-slug <new-slug>` to ingest CLI |

---

## Related Docs

- [RBAC Model](rbac-model.md)
- [Member Management](member-management.md)
- [Token-Based Invites](token-based-invites.md)
- [Workspace Lifecycle](workspace-lifecycle.md)
