# Performance Issues

---

## Slow Time-to-First-Token (TTFT)

Target TTFT: `direct` mode < 1.5s, `research` mode < 5s.

**Diagnostic:**
```bash
# Check recent turn durations
journalctl -u nexus-chat | grep "chat_turn_complete" | tail -10 | jq '.duration_ms'
```

| Cause | Typical added latency | Fix |
|---|---|---|
| Research mode on simple queries | +2–4s | Disable `research_mode_node` or tune routing threshold |
| Qdrant cold start (first query after restart) | +500ms–2s | Expected; warms after first query |
| BM25 rebuilding | +1–30s | Expected on startup; wait for `bm25_rebuild_complete` log |
| High `TOP_K` / `RETRIEVE_K` | +200–500ms per doubling | Lower in dynamic settings |
| Groq rate limit backoff | +5–60s | Check Groq dashboard for quota; use LiteLLM fallback |
| `guardrails_node` running validators | +100–300ms | Disable for non-critical workloads |

---

## BM25 Rebuild Latency

BM25 index rebuilds in memory on process start. Large vaults slow this down:

| Vault size | Rebuild time estimate |
|---|---|
| < 10k chunks | < 5s |
| 10k–50k chunks | 5–30s |
| > 50k chunks | 30–120s |

During rebuild, sparse arm returns empty → RRF runs on dense + graph only. Bot responds but with lower recall.

```bash
# Monitor rebuild progress
journalctl -u nexus-chat -f | grep "bm25"
```

Long-term fix: BM25 persistence (persisted `rank_bm25` snapshot) — currently a known gap.

---

## Qdrant Slow Queries

```bash
# Check Qdrant health and segment count
curl -s http://127.0.0.1:6333/collections/nexus-vault | jq '.result.segments_count'
```

Too many segments → slower search. Trigger optimization:

```bash
curl -X POST http://127.0.0.1:6333/collections/nexus-vault/optimize
```

Also check payload index on `tenant_id` — missing index causes full-collection scan per tenant:

```bash
curl http://127.0.0.1:6333/collections/nexus-vault/index | jq '.result'
# Should show payload_index on tenant_id
```

---

## High Memory Usage

```bash
# Check process memory
ps aux | grep uvicorn
# Check Qdrant container memory
docker stats qdrant-nexus --no-stream
```

| Cause | Fix |
|---|---|
| BM25 index too large | Reduce vault size or increase VPS RAM |
| Qdrant using all RAM | Set `--memory-map-threshold-bytes` in Qdrant config |
| uvicorn worker count too high | Reduce `--workers` in systemd unit (default: 2) |

---

## LiteLLM Fallback Latency

When Groq is degraded, requests fall back to LiteLLM alternative models. Fallback adds 1–3s latency due to retry + reroute.

```bash
# Check LiteLLM logs
docker compose logs --tail=20 nexus-litellm
```

To verify Groq status before blaming NEXUS: check [status.groq.com](https://status.groq.com).

---

## Frontend Slow Load

| Symptom | Cause | Fix |
|---|---|---|
| Initial page load > 3s | Large JS bundle | `npm run build` with `--report` to find large deps |
| Chat page slow on open | Too many conversations in sidebar | Paginate `GET /api/conversations` — default `limit=20` |
| Avatar images slow | Presigned URL generation on every request | Cache avatar URLs client-side for 23h |

---

## Related Docs

- [Stage 3 — Hybrid Retrieval](../02-rag-pipeline/stage-3-hybrid-retrieval.md) — `RETRIEVE_K` tuning
- [Stage 4 — Reranking](../02-rag-pipeline/stage-4-reranking.md) — `TOP_K`, confidence floor
- [Dynamic Settings](../16-configuration-reference/dynamic-settings.md) — runtime tuning params
- [Docker Compose Guide](../12-deployment/docker-compose-guide.md) — Qdrant container config
