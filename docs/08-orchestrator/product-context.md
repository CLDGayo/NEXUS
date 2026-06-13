# Product Context

`inject_product_context_node` fetches relevant products from the workspace catalog and injects them into the LLM context as structured cards — separate from vault document chunks.

---

## When It Runs

- **Toggle gate:** `ai_settings.node_toggles.product_context_node = true`
- Runs after `rerank_node`, before `generate_node`
- Skipped when product catalog is empty for the tenant

---

## Product Matching

Products are matched against the user query using vector similarity:

```python
product_context = await search_products(
    query=state["message"],
    tenant_id=state["tenant_id"],
    top_k=5
)
```

Products are stored in Qdrant alongside vault documents (separate collection or namespace) with deterministic UUIDs derived from `tenant_id + product_id`.

---

## Injected Context Format

Matched products are injected as structured context blocks appended to the system prompt:

```
--- PRODUCT CATALOG ---
[1] Product Name: Pro Package
    Price: $99/month
    Description: Full access to all features with priority support.
    Images: https://assets.nexus.../pro-package.webp
    Checkout: Available

[2] Product Name: Starter Plan
    Price: $29/month
    Description: For small teams getting started.
    Images: https://assets.nexus.../starter.webp
    Checkout: Available
--- END CATALOG ---
```

The LLM is instructed to reference products by name and never invent prices or features not in the catalog.

---

## Carousel Builder

For Messenger surfaces (`surface = "messenger"`), matched products are also formatted as a Messenger generic template carousel:

```json
{
  "attachment": {
    "type": "template",
    "payload": {
      "template_type": "generic",
      "elements": [
        {
          "title": "Pro Package",
          "subtitle": "$99/month — Full access",
          "image_url": "https://assets.nexus.../pro-package.webp",
          "buttons": [
            {
              "type": "postback",
              "title": "Buy Now",
              "payload": "CHECKOUT_pro-package"
            }
          ]
        }
      ]
    }
  }
}
```

The carousel is sent as a separate Messenger message after the text reply (if products were referenced in the response).

---

## Image URL Requirements

Meta requires carousel image URLs to be:
- Publicly accessible (no auth headers)
- Served over HTTPS
- Minimum 1.91:1 aspect ratio recommended (1200×628px)

MinIO presigned URLs are **not suitable** for Messenger carousels (they expire). Images must be served from a stable public CDN path. Set `MINIO_PUBLIC_BASE_URL` to a public-facing base URL.

---

## State Output

```python
state["product_context"] = [
    {
        "id": "uuid",
        "name": "Pro Package",
        "price": 99.00,
        "currency": "USD",
        "description": "...",
        "image_url": "https://...",
        "is_active": True
    },
    ...
]
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No products injected despite catalog populated | Toggle off | Enable `product_context_node` toggle |
| Wrong products matched | Embedding mismatch | Re-sync products: `POST /api/products/{id}/sync` |
| Messenger carousel image broken | Presigned URL expired or private | Use public CDN path via `MINIO_PUBLIC_BASE_URL` |
| LLM inventing product prices | Product not in catalog or context not injected | Verify `state.product_context` populated; check guardrails |

---

## Related Docs

- [Node Toggles](../06-ai-customization/node-toggles.md)
- [Sales Tools](sales-tools.md)
- [Product Catalog](../11-product-catalog/README.md)
- [Outbound Dispatch — Carousel](../07-messenger-integration/outbound-dispatch.md)
