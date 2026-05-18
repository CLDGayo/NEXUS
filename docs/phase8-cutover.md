# Phase 8 — Production Cutover Runbook

End-to-end checklist for putting the docker-compose Nexus v2 stack in front of
live Facebook Messenger traffic at `messenger.nexus.gayo-sphere.cloud`. The v1
systemd `nexus-chat` unit on `chat.nexus.gayo-sphere.cloud:8501` stays
untouched — Phase 8 ships side-by-side.

## Architectural Recap

```
Facebook  ─►  n8n webhook (validates X-Hub-Signature-256 with MESSENGER_APP_SECRET)
              │
              ▼
          n8n HTTP POST  ──►  https://messenger.nexus.gayo-sphere.cloud/webhook/messenger/inbound
              (header: X-Webhook-Api-Key: $WEBHOOK_API_KEY)
              │
              ▼
        nginx (TLS, edge rate-limit) ──► 127.0.0.1:8000 (docker api)
              │
              ▼
        rag.messenger router
              │  (rate-limit → idempotency → PII scrub → LangGraph runner)
              ▼
        outbound_worker  ──►  n8n "Outbound Listener" webhook  ──►  Facebook Send API
```

## Pre-flight Checklist

- [ ] VPS reachable over SSH at `root@72.62.196.231`
- [ ] DNS A record `messenger.nexus.gayo-sphere.cloud → <VPS IP>` propagated
- [ ] `/home/nexus-vault` exists and contains the rsynced vault (created by the
      existing `deploy-rag.sh`)
- [ ] `docker compose version` reports v2.x on the box
- [ ] Free disk ≥ 20 GB (qdrant + langfuse + clickhouse volumes)
- [ ] An n8n workspace where the bridge flow can run

## Step 1 — Pull code + populate `.env.prod`

```bash
ssh root@72.62.196.231
cd /home/nexus-rag
git pull origin main
cp .env.example .env.prod
chmod 600 .env.prod
vi .env.prod      # fill the keys marked REQUIRED in .env.example
```

Mandatory keys (others use defaults from `.env.example`):

| Key | How to fill |
|---|---|
| `WEBHOOK_API_KEY` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | rotate from default |
| `LITELLM_MASTER_KEY` / `LITELLM_SALT_KEY` | rotate from default |
| `GROQ_API_KEY` | from Groq console |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | as needed by `litellm/config.yaml` |
| `LANGFUSE_SALT` | 32-char random |
| `LANGFUSE_ENCRYPTION_KEY` | `openssl rand -hex 32` |
| `LANGFUSE_NEXTAUTH_SECRET` | `openssl rand -hex 32` |
| `OUTBOUND_DISPATCH_ENABLED` | `true` |
| `MAKE_WEBHOOK_URL` | n8n outbound listener URL (filled after Step 5) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | filled after Step 3 (Langfuse first-login) |

## Step 2 — Bring up the docker stack

```bash
cd /home/nexus-rag
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod up -d --build

# wait ~1 min, then verify
docker compose ps                    # every service: healthy or running
docker compose logs --tail=100 api outbound_worker
```

Sanity-check the readiness aggregator from the host:

```bash
curl -s http://127.0.0.1:8000/health/ready | jq .
# expected: {"qdrant":"ok","postgres":"ok","redis":"ok","litellm":"ok"}
```

If any probe reports `fail`, do NOT proceed. Read `docker compose logs
<service>` for the failing component.

## Step 3 — Langfuse first-login + paste keys

1. SSH tunnel locally if needed: `ssh -L 3000:127.0.0.1:3000 root@72.62.196.231`
2. Open http://localhost:3000 → log in with
   `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` (defaults in
   `.env.example` — rotate after first login).
3. Settings → API Keys → "Create new key". Copy public + secret.
4. On the VPS, paste both into `.env.prod` as
   `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.
5. `docker compose -f docker-compose.yml -f docker-compose.prod.yml \
   --env-file .env.prod restart api outbound_worker`

## Step 4 — Stand up nginx + Let's Encrypt

```bash
cp infra/nginx/messenger.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/messenger.conf /etc/nginx/sites-enabled/

# Define the per-IP rate-limit zone the vhost references.
cat > /etc/nginx/conf.d/ratelimit.conf <<'EOF'
limit_req_zone $binary_remote_addr zone=nexus_edge:10m rate=30r/s;
EOF

# Provision LE cert + reload.
certbot --nginx -d messenger.nexus.gayo-sphere.cloud --redirect
nginx -t && systemctl reload nginx

# External smoke.
curl -sI https://messenger.nexus.gayo-sphere.cloud/health   # → HTTP/2 200
```

## Step 5 — Initialize Qdrant collection + ingest the vault

```bash
# Create the collection (idempotent — safe to re-run).
docker compose exec api python -m rag.ingest_v2 init-collection

# Ingest the whole vault. Mounted read-only at /vault.
docker compose exec api python -m rag.ingest_v2 ingest --vault -v

# Verify Qdrant populated.
curl -s http://127.0.0.1:6333/collections/nexus-vault-v2 \
    | jq '.result.points_count'         # > 0

# Verify SQLite wikilink graph populated.
docker compose exec api \
    python -c "import sqlite3; \
               conn = sqlite3.connect('/app/rag/data/nexus_graph.db'); \
               print('edges:', conn.execute('SELECT count(*) FROM edges').fetchone()[0])"
```

## Step 6 — Import the n8n bridge + connect Facebook

1. n8n → Workflows → Import → `automation/n8n/messenger-bridge.json`.
2. Populate the workflow's environment with:
   - `MESSENGER_APP_SECRET` (Meta App dashboard → Settings → Basic)
   - `MESSENGER_PAGE_ACCESS_TOKEN` (Meta App dashboard → Messenger → Settings)
   - `NEXUS_WEBHOOK_URL` = `https://messenger.nexus.gayo-sphere.cloud`
   - `WEBHOOK_API_KEY` = the same value pasted in `.env.prod` on the VPS
   - `N8N_OUTBOUND_LISTENER_URL` = the URL n8n shows under the
     "Outbound Listener (from worker)" webhook node (production URL, not test).
3. Activate the workflow.
4. Copy the inbound webhook URL from the "FB Webhook (Inbound)" node and paste
   it into Meta App dashboard → Messenger → Webhooks. Use
   `MESSENGER_VERIFY_TOKEN` for the verification challenge.
5. Subscribe the Page to the `messages`, `messaging_postbacks` fields.
6. Back on the VPS, set `.env.prod`:
   `MAKE_WEBHOOK_URL=<the N8N_OUTBOUND_LISTENER_URL value>`
   then `docker compose ... restart outbound_worker`.

## Step 7 — Smoke test the live surface

```bash
# On any machine with WEBHOOK_API_KEY in env.
export WEBHOOK_API_KEY=...
bash scripts/smoke-test.sh https://messenger.nexus.gayo-sphere.cloud
```

Expected (all green):

| Test | Pass criterion |
|---|---|
| auth enforcement | POST without header → 401/403/503 |
| PII scrub | 200 reply, Langfuse trace shows `[EMAIL_REDACTED]` / `[CARD_REDACTED]` |
| idempotency | second POST with same correlation_id → `status="duplicate"` |
| rate limit | burst > `MESSENGER_RATE_LIMIT_PER_MIN` triggers ≥ 1 × 429 |

## Step 8 — Live Messenger demo

From a personal FB account that's allowed to message the Page (or while the
app is in dev mode, a test user) send a few messages:

- A simple factual question that the vault covers → expect cited reply.
- A question the vault cannot answer → expect honest abstention.
- A message containing an email + a Luhn-valid test card
  (`4111 1111 1111 1111`) → in Langfuse, confirm the trace text is redacted.
- A rapid burst of 25+ messages → Langfuse should show some requests denied
  by the rate limiter.

While testing, tail the logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod logs -f api outbound_worker
```

And watch the n8n "Executions" tab for the inbound and outbound roundtrip.

## Rollback

If anything misbehaves, the docker stack is fully reversible without touching
v1:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod down

rm /etc/nginx/sites-enabled/messenger.conf
systemctl reload nginx
```

`chat.nexus.gayo-sphere.cloud:8501` (v1 systemd `nexus-chat`) never changed.

## Out-of-Scope Reminders

- Facebook `X-Hub-Signature-256` HMAC validation is done by **n8n**, not
  FastAPI. If we ever cut n8n out and have Facebook POST directly to our
  FastAPI, `rag/messenger/security.py` must gain that check.
- Cross-encoder reranking + BM25 hybrid retrieval, RAGAS eval CI gate, and
  full Tempo/Jaeger OTel backend land in Phase 9.
- The `otel-collector` service itself is not in docker-compose yet — the
  config at `otel/otel-collector-config.yaml` is ready, the service stanza
  ships in Phase 9.
