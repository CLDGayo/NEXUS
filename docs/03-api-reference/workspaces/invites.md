# Invites

Token-based workspace invitations. An invite generates a SHA-256 token, sends an email via n8n, and creates a public `/join` URL the recipient clicks to accept.

---

## Create Invite

```
POST /api/tenants/{id}/invites
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

```json
{
  "email": "charlie@example.com",
  "role": "member"
}
```

| Field | Type | Required | Values |
|---|---|---|---|
| `email` | string | Yes | Must be valid email |
| `role` | string | No | `member` (default) or `admin` |

**Response:**
```json
{
  "invite_id": "uuid",
  "email": "charlie@example.com",
  "role": "member",
  "expires_at": "2026-06-21T00:00:00Z",
  "join_url": "https://chat.nexus.gayo-sphere.cloud/join?token=abc123"
}
```

`expires_at` is 7 days from creation. After expiry the token is invalid and must be re-sent.

**What happens:**
1. Random 32-byte token generated; SHA-256 hash stored in `app.tenant_invites.token_hash`
2. Raw token included in `join_url` (never stored)
3. n8n email webhook fired with `join_url` and inviter details
4. n8n sends email to recipient

**RBAC:** `admin` or `owner`

---

## List Invites

```
GET /api/tenants/{id}/invites
Authorization: Bearer {jwt_token}
```

**Response:**
```json
{
  "invites": [
    {
      "id": "uuid",
      "email": "charlie@example.com",
      "role": "member",
      "status": "pending",
      "expires_at": "2026-06-21T00:00:00Z",
      "created_at": "2026-06-14T00:00:00Z"
    }
  ]
}
```

`status` values: `pending`, `accepted`, `expired`, `revoked`

---

## Revoke Invite

```
DELETE /api/tenants/{id}/invites/{invite_id}
Authorization: Bearer {jwt_token}
```

Sets `status = revoked`. The `join_url` becomes invalid immediately.

**Response:** `204 No Content`

---

## Accept Invite (Public)

```
POST /api/invites/accept
Content-Type: application/json
```

```json
{ "token": "raw-token-from-join-url" }
```

This endpoint is **unauthenticated**. The user must be logged in (session cookie checked) or is prompted to register first. After acceptance:

1. Token SHA-256 hash matched against `app.tenant_invites`
2. Expiry checked
3. `app.tenant_members` record created with specified role
4. Invite status set to `accepted`
5. User redirected to workspace

**`/join` route:** The frontend `/join?token=abc` route handles display (workspace name, inviter) and calls `POST /api/invites/accept` on confirmation.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Create/list/revoke: missing token |
| `403` | Insufficient role for create/revoke |
| `404` | Invite not found |
| `409` | User already a member of this tenant |
| `410` | Token expired or revoked (accept endpoint) |
| `422` | Invalid email format |

---

## Related Docs

- [Token-Based Invites Guide](../../04-workspace-management/token-based-invites.md)
- [Members](members.md)
- [n8n Automation](../../10-integrations/n8n-automation.md)
