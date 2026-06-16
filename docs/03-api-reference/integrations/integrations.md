# Integrations API

Manage external integration connections for a workspace. Currently surfaces the Messenger (Meta) integration with sub-routes for page management and webhook setup.

---

## List Integration Catalog

```
GET /api/integrations/catalog
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

Returns available integrations and their status. This endpoint is read-only and returns no credentials.

```json
{
  "integrations": [
    {
      "id": "messenger",
      "name": "Meta Messenger",
      "status": "active",
      "tier": "standard",
      "description": "Connect a Facebook Page to receive and reply to messages via NEXUS AI."
    },
    {
      "id": "hunter",
      "name": "Hunter.io",
      "status": "coming_soon",
      "tier": "enterprise"
    }
  ]
}
```

---

## Get Integration Config

```
GET /api/integrations/{integration_id}
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

Returns the workspace's current configuration for an integration. Sensitive fields (tokens, secrets) are masked with `***`.

---

## Update Integration Config

```
PATCH /api/integrations/{integration_id}
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

```json
{
  "page_id": "12345678",
  "page_access_token": "EAABsb..."
}
```

Stores encrypted credentials in `app.integrations`. Returns the updated config with secrets masked.

---

## Test Integration

```
POST /api/integrations/{integration_id}/test
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

Runs a lightweight liveness check — for Messenger, sends a Graph API `me` request with the stored token.

```json
{
  "status": "ok",
  "latency_ms": 142,
  "details": "Page: My Business Page (ID: 12345678)"
}
```

---

## Messenger Sub-Routes

The Messenger integration has additional sub-routes under `/api/integrations/messenger/`:

| Route | Method | Purpose |
|---|---|---|
| `/pages` | GET | List connected Facebook Pages |
| `/pages` | POST | Connect a new Page |
| `/pages/{page_id}` | DELETE | Disconnect a Page |
| `/webhook` | POST | Meta webhook verification + event intake |

> **📝 NOTE:** The `/webhook` sub-route is a public endpoint — Meta's servers POST here directly. It is excluded from auth middleware and verified via HMAC-SHA256 `X-Hub-Signature-256` header.

---

## Permissions

All integration management endpoints require `require_owner`. Testing (`/test`) requires `require_manager`.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Insufficient role |
| `404` | Integration ID not found |
| `422` | Invalid config payload |
| `502` | External service unreachable during test |

---

## Related Docs

- [Messenger Integration Overview](../../07-messenger-integration/README.md)
- [Meta Webhook Setup](../../07-messenger-integration/meta-webhook-setup.md)
- [Security & PII](../../07-messenger-integration/security-pii.md)
