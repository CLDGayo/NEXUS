# Member Management

Admins and owners can list, invite, change roles, and remove members from a workspace. All operations require the `admin` or `owner` role (`require_manager` dependency).

---

## List Members

```http
GET /api/tenants/{tenant_id}/members
Authorization: Bearer <manager-jwt>
```

Response:

```json
[
  {
    "user_id": "550e8400-...",
    "email": "admin@example.com",
    "display_name": "Alice",
    "profile_image_url": "https://assets.nexus.gayo-sphere.cloud/avatars/alice.webp",
    "role": "owner",
    "joined_at": "2026-01-15T10:00:00Z"
  },
  {
    "user_id": "661f9511-...",
    "email": "bob@example.com",
    "display_name": "Bob",
    "profile_image_url": null,
    "role": "member",
    "joined_at": "2026-06-01T09:00:00Z"
  }
]
```

---

## Change a Member's Role

```http
PATCH /api/tenants/{tenant_id}/members/{user_id}
Authorization: Bearer <manager-jwt>
Content-Type: application/json

{
  "role": "admin"
}
```

**Valid values:** `admin`, `member`

**Constraints:**
- Cannot change the owner's role via this endpoint — use ownership transfer
- Admins can change `member` → `admin` or `admin` → `member`
- The caller cannot change their own role

**Response:** `200 OK` with updated member object.

---

## Remove a Member

```http
DELETE /api/tenants/{tenant_id}/members/{user_id}
Authorization: Bearer <manager-jwt>
```

**Constraints:**
- Cannot remove the owner — transfer ownership first, then remove
- Members can be removed by `admin` or `owner`

**Response:** `204 No Content`

After removal, the user's data (conversations, uploads) remains in the workspace — it is not deleted. The user simply loses access.

---

## Self-Removal

Members can leave a workspace by removing themselves:

```http
DELETE /api/tenants/{tenant_id}/members/{my_user_id}
Authorization: Bearer <my-jwt>
```

The owner cannot leave without first transferring ownership.

---

## Adding Members via Invite

Direct member creation is not supported. New members must be added via the invite flow:

1. `POST /api/tenants/{id}/invites` — creates invite + sends email
2. Invitee accepts via `/join?token=...`
3. `TenantUser` row is created with the specified role

→ See [Token-Based Invites](token-based-invites.md)

---

## Role Change Audit

Role changes are logged to `app.logs` for audit purposes. Each change records:
- `action: "role_change"`
- `actor_id` (who made the change)
- `target_user_id`
- `old_role` / `new_role`
- `tenant_id`
- `timestamp`

Retrieve the audit log via `GET /api/logs` (requires `manager` role).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 Manager role required` | Caller is `member` | Request admin promotion from workspace owner |
| `404 Not Found` on member | User not in workspace | Verify user_id via `GET /api/tenants/{id}/members` |
| Cannot remove owner | Removing owner directly | Transfer ownership first via `POST /api/tenants/{id}/transfer` |
| `409 Already a member` | User already in workspace | User already joined — check member list |

---

## Related Docs

- [Token-Based Invites](token-based-invites.md)
- [RBAC Model](rbac-model.md)
- [Danger Zone — Ownership Transfer](danger-zone.md)
