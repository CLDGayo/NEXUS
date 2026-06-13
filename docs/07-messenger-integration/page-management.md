# Page Management

Each Meta Page must be bound to a NEXUS workspace (tenant) before messages are routed. One page maps to exactly one tenant.

---

## Bind a Page

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/integrations/messenger/pages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "page_id": "123456789012345",
    "page_name": "Acme Corp",
    "tenant_id": "your-tenant-uuid"
  }'
```

**Response:**

```json
{
  "id": "integration-uuid",
  "page_id": "123456789012345",
  "page_name": "Acme Corp",
  "tenant_id": "your-tenant-uuid",
  "created_at": "2026-06-13T00:00:00Z"
}
```

Inbound messages from this page now route to the `acme-corp` workspace.

---

## List Bound Pages

```bash
curl https://chat.nexus.gayo-sphere.cloud/api/integrations/messenger/pages \
  -H "Authorization: Bearer $TOKEN"
```

Returns all page bindings for the caller's tenant.

---

## Unbind a Page

```bash
curl -X DELETE https://chat.nexus.gayo-sphere.cloud/api/integrations/messenger/pages/{page_id} \
  -H "Authorization: Bearer $TOKEN"
```

After unbinding, inbound messages from that page are acknowledged but not processed (no route → logged as unbound). Returns `204 No Content`.

---

## One-Page-Per-Tenant Constraint

| Constraint | Enforcement |
|---|---|
| One page → one tenant | `UNIQUE(page_id)` on `app.integrations` |
| One tenant → one page | Application-layer check (one Messenger integration per tenant) |

Attempting to bind a page already bound to another tenant returns `409 Conflict`.

---

## Page Routing Logic

On every inbound webhook event, NEXUS resolves the tenant from the page ID:

```python
page_binding = await db.scalar(
    select(Integration)
    .where(Integration.provider == "messenger")
    .where(Integration.external_id == page_id)
)
if not page_binding:
    logger.warning(f"Unbound page: {page_id}")
    return  # Acknowledge; no processing
tenant_id = page_binding.tenant_id
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `409 Conflict` on bind | Page already bound to another tenant | Unbind from current tenant first |
| Messages not routing to workspace | Page not bound | Verify with `GET /api/integrations/messenger/pages` |
| Wrong workspace receiving messages | Page bound to wrong tenant | Unbind + rebind to correct tenant |

---

## Related Docs

- [Meta Webhook Setup](meta-webhook-setup.md) — webhook URL + page token config
- [Inbound Message Flow](inbound-message-flow.md)
- [Workspace Management](../04-workspace-management/README.md)
