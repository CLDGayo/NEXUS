# Qdrant Sync

Product records are embedded into the `nexus-vault` Qdrant collection alongside document chunks. This enables `inject_product_context_node` to surface relevant products in chat responses.

---

## How Sync Works

Every create/update to a product triggers `upsert_product_to_qdrant()` as a background task:

1. Construct embedding text: `"{name}\n{description}\nPrice: {price} {currency}"`
2. Embed via fastembed `BAAI/bge-small-en-v1.5` (same model as documents)
3. Upsert to Qdrant with deterministic UUID (derived from `product_id`)
4. Set payload: `{tenant_id, source_kind: "product", product_id, name, price, is_active}`

---

## Deterministic UUIDs

Product vectors use UUID5 (namespace + product_id string) so upsert is idempotent:

```python
import uuid

PRODUCT_NS = uuid.UUID("product-namespace-uuid-here")

def product_vector_id(product_id: str) -> str:
    return str(uuid.uuid5(PRODUCT_NS, product_id))
```

Re-syncing the same product always overwrites the same vector point — no duplicates.

---

## Payload Filter

`inject_product_context_node` queries Qdrant with:

```python
{
    "must": [
        {"key": "tenant_id", "match": {"value": tenant_id}},
        {"key": "source_kind", "match": {"value": "product"}},
        {"key": "is_active", "match": {"value": True}}
    ]
}
```

Archived products (`is_active=false`) are excluded at query time. Their vectors remain in Qdrant with updated payload.

---

## Manual Sync

If a product's Qdrant vector is out of sync (e.g., after bulk import or Qdrant downtime):

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/products/{id}/sync \
  -H "Authorization: Bearer $TOKEN"
```

Or full catalog re-sync for tenant (admin-only):

```bash
curl -X POST https://chat.nexus.gayo-sphere.cloud/api/products/sync-all \
  -H "Authorization: Bearer $TOKEN"
```

---

## Sync Failure Handling

Background sync failures are logged but do not fail the API request. The Postgres record is always written first (authoritative source). If Qdrant is unreachable:

- Create/update still returns `200`
- Log entry: `product_qdrant_sync_failed {product_id}`
- Product surfaces in chat only after successful sync

Check sync status:
```bash
journalctl -u nexus-chat | grep "product_qdrant_sync"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Product not appearing in chat | Qdrant sync failed at create time | `POST /api/products/{id}/sync` |
| Stale price in product context | Sync not triggered after PATCH | Verify PATCH response; trigger manual sync |
| All products missing from chat | `source_kind` payload missing (old data) | Run `sync-all` to backfill payload |
| Duplicate product results | UUID generation changed | Check `PRODUCT_NS` constant hasn't changed; `sync-all` to re-upsert |

---

## Related Docs

- [Product Management](product-management.md)
- [Product Context Node](../08-orchestrator/product-context.md)
- [Stage 3 — Hybrid Retrieval](../02-rag-pipeline/stage-3-hybrid-retrieval.md) — same Qdrant collection
