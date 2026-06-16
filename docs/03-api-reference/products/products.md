# Product Catalog API

CRUD for tenant products. Products are shown in LLM context during retrieval and exposed via Messenger carousel replies.

---

## List Products

```
GET /api/products
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

### Response

```json
{
  "products": [
    {
      "id": "uuid",
      "name": "Premium Plan",
      "description": "Full access to all features.",
      "price": 49.99,
      "currency": "USD",
      "image_url": "https://chat.nexus.gayo-sphere.cloud/static/products/uuid.webp",
      "active": true,
      "created_at": "2026-05-01T00:00:00Z"
    }
  ],
  "total": 12
}
```

---

## Create Product

```
POST /api/products
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

```json
{
  "name": "Premium Plan",
  "description": "Full access to all features.",
  "price": 49.99,
  "currency": "USD",
  "active": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Max 120 chars |
| `description` | string | No | Markdown supported; shown to LLM and in carousel |
| `price` | number | No | Decimal; omit for free/contact-for-pricing products |
| `currency` | string | No | ISO 4217 code; default `"USD"` |
| `active` | boolean | No | Default `true`; inactive products excluded from LLM context |

Returns created product object with `id` and `created_at`.

---

## Update Product

```
PATCH /api/products/{product_id}
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: application/json
```

Partial update — only supplied fields are modified.

---

## Delete Product

```
DELETE /api/products/{product_id}
Authorization: Bearer {jwt_token} | nxs_{api_token}
```

Returns `204 No Content`. Immediately removes the product from LLM context on the next chat request.

---

## Upload Product Image

```
POST /api/products/{product_id}/image
Authorization: Bearer {jwt_token} | nxs_{api_token}
Content-Type: multipart/form-data
```

```bash
curl -X POST .../api/products/{id}/image \
  -H "Authorization: Bearer $TOKEN" \
  -F "image=@product-shot.webp"
```

- Accepted formats: WebP (preferred), JPEG, PNG
- Max size: 5 MB
- Stored in MinIO at `{tenant_id}/products/{product_id}.webp`
- `image_url` in subsequent GET responses points to the presigned CDN URL

---

## Permissions

All product endpoints require `require_manager` (owner or admin). Members can only see products through the chat surface, not manage them.

---

## Error Responses

| HTTP code | Cause |
|---|---|
| `401` | Missing or expired token |
| `403` | Member role |
| `404` | Product not found in this workspace |
| `413` | Image exceeds 5 MB |
| `415` | Unsupported image format |
| `422` | Validation error (missing `name`, etc.) |

---

## Related Docs

- [Product Catalog (conceptual)](../../11-product-catalog/product-management.md)
- [Image Management](../../11-product-catalog/image-management.md)
- [Product Context node](../../08-orchestrator/product-context.md)
