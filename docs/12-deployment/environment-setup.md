# Environment Setup

NEXUS uses `.env` files for secrets and configuration. Mac dev and VPS prod use different values for several keys.

---

## File Locations

| Environment | Path | Managed by |
|---|---|---|
| Mac dev | `rag/.env` | Developer (gitignored) |
| VPS prod | `/home/nexus-rag/.env` | Preserved across deploys (`rsync --exclude='.env'`) |

> **⚠️ WARNING:** Never commit `.env` to git. The `.gitignore` excludes `rag/.env`. Verify with `git status` before committing.

---

## Full `.env` Template

```bash
# ── LLM ──────────────────────────────────────────────────────
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
FOLLOWUP_MODEL=llama-3.1-8b-instant

# ── Vector Store ─────────────────────────────────────────────
# Mac dev:
QDRANT_URL=https://qdrant.nexus.gayo-sphere.cloud:443
QDRANT_API_KEY=your_qdrant_api_key
# VPS prod (replace above with):
# QDRANT_URL=http://127.0.0.1:6333
# QDRANT_API_KEY=          # leave empty for local-only access

QDRANT_COLLECTION=nexus-vault
EMBED_MODEL=BAAI/bge-small-en-v1.5

# ── Database ─────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://nexus_rag:password@localhost:5432/nexus_rag

# ── Auth ─────────────────────────────────────────────────────
JWT_SECRET=your_jwt_secret_at_least_32_bytes_long
NEXUS_PASSWORD=your_admin_password

# ── Vault ────────────────────────────────────────────────────
# Mac dev:
VAULT_PATH=/Users/you/Gayo\ Sphere/Second\ Brain\ Nexus
# VPS prod:
# VAULT_PATH=/home/nexus-vault

# ── Object Storage (MinIO) ───────────────────────────────────
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_AVATARS=nexus-avatars
MINIO_PUBLIC_BASE_URL=https://assets.nexus.gayo-sphere.cloud

# ── Redis ────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379

# ── Messenger ────────────────────────────────────────────────
MESSENGER_APP_ID=your_meta_app_id
MESSENGER_APP_SECRET=your_meta_app_secret
MESSENGER_VERIFY_TOKEN=your_verify_token
MESSENGER_PAGE_TOKEN=your_page_access_token
HITL_PAUSE_DURATION_S=3600

# ── n8n Webhooks ─────────────────────────────────────────────
N8N_WEBHOOK_CHECKOUT_URL=https://n8n.example.com/webhook/checkout
N8N_WEBHOOK_LEAD_URL=https://n8n.example.com/webhook/lead
N8N_WEBHOOK_NOTIFY_URL=https://n8n.example.com/webhook/hitl-notify

# ── Observability (optional) ─────────────────────────────────
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# ── LiteLLM proxy (optional) ─────────────────────────────────
LITELLM_PROXY_URL=http://localhost:4000
LITELLM_API_KEY=your_litellm_key
```

---

## Mac Dev vs VPS Prod Differences

| Variable | Mac dev | VPS prod |
|---|---|---|
| `QDRANT_URL` | `https://qdrant.nexus.gayo-sphere.cloud:443` | `http://127.0.0.1:6333` |
| `QDRANT_API_KEY` | Required (public endpoint) | Empty (local Docker) |
| `VAULT_PATH` | Local disk path | `/home/nexus-vault` |
| `MINIO_ENDPOINT` | `localhost:9000` | `localhost:9000` (Docker) |
| `DATABASE_URL` | Local Postgres or Docker | `localhost:5432` (host Postgres) |

---

## Systemd EnvironmentFile

On the VPS, systemd loads `.env` directly:

```ini
# /etc/systemd/system/nexus-chat.service (excerpt)
[Service]
EnvironmentFile=/home/nexus-rag/.env
ExecStart=/home/nexus-rag/.local/bin/uv run uvicorn app:app \
    --host 127.0.0.1 --port 8501
WorkingDirectory=/home/nexus-rag/rag
User=nexus-rag
Restart=always
```

After changing `.env` on VPS:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nexus-chat
```

---

## Secret Rotation

| Secret | Rotation procedure |
|---|---|
| `JWT_SECRET` | Update `.env`; restart service; all existing JWT tokens are immediately invalidated |
| `GROQ_API_KEY` | Revoke in Groq dashboard; generate new; update `.env`; restart |
| `MESSENGER_APP_SECRET` | Regenerate in Meta Dashboard; update `.env`; restart |
| `MINIO_SECRET_KEY` | Update in MinIO console + `.env`; restart |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `KeyError: 'GROQ_API_KEY'` on start | `.env` not loaded | Check `WorkingDirectory` in systemd unit; verify `.env` exists at path |
| Auth fails after restart | `JWT_SECRET` changed | Expected — all users must re-login |
| Qdrant connection refused on VPS | Using Mac dev `QDRANT_URL` on VPS | Switch to `http://127.0.0.1:6333` on VPS |

---

## Related Docs

- [Environment Variables — Full Reference](../16-configuration-reference/environment-variables.md)
- [Prerequisites](prerequisites.md)
- [RAG Deployment](rag-deployment.md)
