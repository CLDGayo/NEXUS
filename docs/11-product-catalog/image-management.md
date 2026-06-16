# Image Management

Product images are stored in MinIO under `tenants/{slug}/products/{product_id}/` and served via presigned URLs.

---

## Upload Image

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/products/{id}/images \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@product-hero.webp"
```

**Response:**
```json
{
  "image_url": "https://minio.nexus.gayo-sphere.cloud/nexus/tenants/acme-corp/products/uuid/0.webp?X-Amz-...",
  "display_order": 0
}
```

---

## Storage Details

| Detail | Value |
|---|---|
| Format | WebP (converted server-side from any input format) |
| Max file size | 5MB |
| MinIO path | `tenants/{tenant_slug}/products/{product_id}/{display_order}.webp` |
| URL type | Presigned (expires in 23 hours) |
| Multiple images | Supported — upload multiple files; `display_order` increments per upload |

---

## Display Order

Images are ordered by `display_order` (0-indexed). First image (`display_order=0`) is used as:
- Primary product thumbnail in chat responses
- First carousel card in Messenger

Reorder via:
```bash
curl -X PATCH https://chat.nexus.gayo-sphere.cloud/api/products/{id}/images/reorder \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"order": ["uuid-img-2", "uuid-img-0", "uuid-img-1"]}'
```

---

## Delete Image

```bash
curl -X DELETE https://chat.nexus.gayo-sphere.cloud/api/products/{id}/images/{image_id} \
  -H "Authorization: Bearer $TOKEN"
```

Deletes from MinIO and removes from `app.product_images`. Remaining images are reordered to fill gap.

---

## Presigned URL Expiry Warning

> **CRITICAL:** Presigned URLs expire after 23 hours. Do **not** store presigned URLs in client-side state across sessions — always fetch fresh product data on load.
>
> **Messenger carousels:** Meta fetches carousel image URLs at send time. If the presigned URL expires before Meta fetches the image, the carousel card shows a broken image. To avoid this: either use public bucket URLs (no presigning) or ensure Messenger messages are sent within the presigned URL lifetime.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Broken image in Messenger carousel | Presigned URL expired before Meta fetch | Use public bucket policy for product images bucket |
| `413 Request Entity Too Large` | Image > 5MB | Resize before upload |
| Wrong format stored | Non-WebP input rejected | Server converts on ingest; check `Content-Type` header |
| Image not appearing in chat | `display_order=0` not set | Confirm `GET /api/products/{id}` returns `image_urls` with at least one entry |

---

## Related Docs

- [Product Management](product-management.md)
- [Product Context Node](../08-orchestrator/product-context.md)
- [Docker Compose Guide](../12-deployment/docker-compose-guide.md) — MinIO service config
