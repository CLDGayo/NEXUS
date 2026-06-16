# Product Management

---

## Create Product

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/products \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Pro Package",
    "slug": "pro-package",
    "description": "Full-featured plan with unlimited RAG queries and 3 workspaces.",
    "price": 99.00,
    "currency": "USD",
    "metadata": { "tier": "pro", "seats": 5 }
  }'
```

**Response:**
```json
{
  "id": "uuid",
  "slug": "pro-package",
  "name": "Pro Package",
  "price": 99.00,
  "is_active": true,
  "created_at": "2026-06-14T00:00:00Z"
}
```

---

## Slug Rules

- Auto-generated from `name` if not provided: `"Pro Package"` → `"pro-package"`
- Unique per tenant (UNIQUE constraint on `(tenant_id, slug)`)
- Immutable after creation — changing a slug creates a new product record
- URL-safe: lowercase, hyphens only, no spaces or special characters

---

## List Products

```bash
GET /api/products
GET /api/products?is_active=true      # active only (default)
GET /api/products?is_active=false     # archived only
```

Returns array ordered by `created_at DESC`. No pagination currently — keep catalog under 500 products per tenant for performance.

---

## Update Product

```bash
curl -X PATCH https://chat.nexus.gayo-sphere.cloud/api/products/{id} \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"price": 119.00, "description": "Updated description."}'
```

Partial update — only provided fields change. After update, Qdrant embedding is re-synced automatically (background task).

**Updatable fields:** `name`, `description`, `price`, `currency`, `metadata`, `is_active`

**Non-updatable:** `id`, `slug`, `tenant_id`, `created_at`

---

## Archive Product

Soft-delete via `is_active=false`:

```bash
curl -X PATCH https://chat.nexus.gayo-sphere.cloud/api/products/{id} \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"is_active": false}'
```

Archived products:
- Hidden from `inject_product_context_node` Qdrant search
- Not returned in default `GET /api/products`
- Still returned with `?is_active=false` for admin review
- Qdrant payload updated to `is_active: false` (not deleted from vector store)

---

## RBAC

| Action | Required role |
|---|---|
| List products | `member` (any authenticated user) |
| Create / update / archive | `admin` or `owner` |
| Hard-delete (not exposed in API) | N/A — archive instead |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `409 Conflict` on create | Slug already exists in tenant | Provide unique `slug` or let system auto-generate |
| Product not surfacing in chat | Qdrant sync failed or `is_active=false` | Check `GET /api/products/{id}`; trigger manual sync via `POST /api/products/{id}/sync` |
| Price mismatch in chat response | ExactMatchValidator rejecting old price | Update price via PATCH; Qdrant sync re-embeds description with new price |

---

## Related Docs

- [Image Management](image-management.md)
- [Qdrant Sync](qdrant-sync.md)
- [Product Context Node](../08-orchestrator/product-context.md)
