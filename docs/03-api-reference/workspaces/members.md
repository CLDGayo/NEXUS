# Members

Manage workspace membership. Members are users with an `app.tenant_members` record linking them to a tenant with a role.

---

## List Members

```
GET /api/tenants/{id}/members
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "members": [
    {
      "user_id": "uuid",
      "email": "alice@example.com",
      "role": "owner",
      "joined_at": "2026-06-01T00:00:00Z"
    },
    {
      "user_id": "uuid",
      "email": "bob@example.com",
      "role": "member",
      "joined_at": "2026-06-10T00:00:00Z"
    }
  ],
  "total": 2
}
```

All authenticated members of the tenant can list members.

---

## Update Member Role

```
PATCH /api/tenants/{id}/members/{user_id}
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{ "role": "admin" }
```

| Transition | Who can perform |
|---|---|
| `member` → `admin` | `owner` or `admin` |
| `admin` → `member` | `owner` or `admin` |
| `member/admin` → `owner` | `owner` only (triggers ownership transfer) |
| Any → `owner` | Use `/lifecycle/transfer-owner` instead |

**RBAC:** `admin` or `owner`

---

## Remove Member

```
DELETE /api/tenants/{id}/members/{user_id}
Authorization: Bearer {jwt_token}
```

Removes user from `app.tenant_members`. Does not delete the user account.

**Constraints:**
- Cannot remove the last `owner`
- Cannot remove yourself if you are the only `owner` — transfer ownership first
- Removes all API tokens scoped to this tenant for that user

**RBAC:** `admin` or `owner`

**Response:** `204 No Content`

---

## Leave Workspace

A member can remove themselves:

```
DELETE /api/tenants/{id}/members/me
Authorization: Bearer {jwt_token}
```

Same constraints as above — owner cannot leave if sole owner.

---

## Role Permission Matrix

| Action | member | admin | owner |
|---|---|---|---|
| View documents | ✓ | ✓ | ✓ |
| Upload documents | — | ✓ | ✓ |
| Manage members | — | ✓ | ✓ |
| Change settings | — | ✓ | ✓ |
| Archive workspace | — | — | ✓ |
| Delete workspace | — | — | ✓ |
| Transfer ownership | — | — | ✓ |

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Insufficient role |
| `404` | Member not found in this tenant |
| `409` | Cannot remove sole owner |

---

## Related Docs

- [Token-Based Invites](invites.md)
- [RBAC Model](../../04-workspace-management/rbac-model.md)
- [Member Management Guide](../../04-workspace-management/member-management.md)
