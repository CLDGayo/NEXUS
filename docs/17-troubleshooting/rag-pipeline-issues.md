# RAG Pipeline Issues

---

## Low Recall / Irrelevant Results

| Symptom | Check | Fix |
|---|---|---|
| Bot answers off-topic | `GET /api/documents/index_summary` — chunk count low? | Re-ingest: `uv run python -m rag.ingest` |
| Relevant docs exist but not retrieved | Qdrant collection wrong tenant filter | Verify `tenant_id` payload field on points matches slug |
| BM25 returning nothing | In-memory BM25 empty (process just started) | Wait 30–60s for BM25 to rebuild from Qdrant scroll; or restart triggers rebuild |
| Graph arm returning 0 results | `app.document_links` table empty | Run wikilink extractor: `uv run python -m rag.ingest_v2.wikilinks` |
| Dense arm score too low | `RERANK_CONFIDENCE_FLOOR` too high | Lower `RERANK_CONFIDENCE_FLOOR` in `app.settings` |

---

## Hallucination / Phantom Facts

| Symptom | Likely cause | Fix |
|---|---|---|
| Response states price not in catalog | `ExactMatchValidator` disabled | Enable `guardrails_node` toggle |
| Response cites `[4]` but only 3 chunks returned | Model ignoring citation instruction | Check system prompt citation enforcement; ensure `guardrails_node` enabled |
| Response references product not in vault | Product not ingested into Qdrant | `POST /api/products/{id}/sync` |

---

## All Responses Abstaining

```bash
# Check guardrail pass rate
curl "https://chat.nexus.gayo-sphere.cloud/api/logs?event_type=guardrail_failed" \
  -H "Authorization: Bearer $TOKEN" | jq 'length'
```

| Cause | Fix |
|---|---|
| `RERANK_CONFIDENCE_FLOOR` too high — all chunks dropped | Lower floor: `PATCH /api/settings` `{"RERANK_CONFIDENCE_FLOOR": "0.1"}` |
| `ENTROPY_THRESHOLD` too low | Raise threshold in dynamic settings |
| Vault empty or ingest failed | Check `index_summary`; re-run ingest |

---

## BM25 Cold Start

BM25 rebuilds in memory on process start. During rebuild (~5–30s on large vaults), sparse arm returns empty:

```bash
# Check logs for rebuild completion
journalctl -u nexus-chat | grep "bm25_rebuild"
```

Not a bug — expected behavior. Large vaults (>50k chunks) may take longer. BM25 persistence is a known gap (see [all-context.md](../../process/context/all-context.md#open-questions)).

---

## Reranker Abstaining Everything

```bash
# Check rerank scores
journalctl -u nexus-chat | grep "rerank_complete" | tail -5
```

If all scores below floor:
1. Check `RERANK_CONFIDENCE_FLOOR` — lower if needed
2. Verify reranker model loaded: `fastembed TextCrossEncoder` needs ~100ms on first call
3. Check `EMBED_MODEL` matches what was used during ingest

---

## Related Docs

- [Stage 3 — Hybrid Retrieval](../02-rag-pipeline/stage-3-hybrid-retrieval.md)
- [Stage 4 — Reranking](../02-rag-pipeline/stage-4-reranking.md)
- [Guardrails](../14-guardrails/README.md)
- [Dynamic Settings](../16-configuration-reference/dynamic-settings.md)
