# RAG Deployment

`deploy-rag.sh` deploys the FastAPI RAG application to the VPS. It syncs code and vault, runs Alembic migrations, and restarts the systemd service.

---

## What the Script Does

```bash
./deploy-rag.sh
```

1. `rsync` code from Mac to VPS (`/home/nexus-rag/`) — excludes `.env`, `__pycache__`, `.venv`
2. `rsync` vault from Mac to VPS (`/home/nexus-vault/`) — excludes `.git`, `.obsidian`
3. SSH to VPS:
   a. `uv sync` — install/update Python dependencies from `uv.lock`
   b. `alembic upgrade head` — run pending migrations
   c. `uv run python -m rag.ingest` — re-ingest updated vault files
   d. `sudo systemctl restart nexus-chat` — restart the service
4. Smoke check: `curl -sSI https://chat.nexus.gayo-sphere.cloud/` → expect `200`

---

## Script Internals

```bash
#!/usr/bin/env bash
set -euo pipefail

VPS_USER="nexus-rag"
VPS_HOST="72.62.196.231"
VPS_CODE="/home/nexus-rag"
VPS_VAULT="/home/nexus-vault"
LOCAL_VAULT="/Users/clarencelloydgayo/Gayo Sphere/Second Brain Nexus"

echo "==> Syncing code..."
rsync -avz --delete \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='*.pyc' \
  --exclude='.git' \
  "rag/" "$VPS_USER@$VPS_HOST:$VPS_CODE/rag/"

echo "==> Syncing vault..."
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.obsidian' \
  --exclude='.trash' \
  "$LOCAL_VAULT/" "$VPS_USER@$VPS_HOST:$VPS_VAULT/"

echo "==> Running remote steps..."
ssh "$VPS_USER@$VPS_HOST" bash <<'REMOTE'
  set -euo pipefail
  cd /home/nexus-rag/rag
  uv sync
  uv run alembic upgrade head
  uv run python -m rag.ingest
  sudo systemctl restart nexus-chat
REMOTE

echo "==> Smoke check..."
curl -sSI https://chat.nexus.gayo-sphere.cloud/ | head -1
echo "Deploy complete."
```

---

## Partial Deploys

To skip vault sync (code-only deploy):

```bash
SKIP_VAULT=1 ./deploy-rag.sh
```

To skip ingest (migrations + restart only):

```bash
SKIP_INGEST=1 ./deploy-rag.sh
```

> **📝 NOTE:** If vault content changed but ingest is skipped, Qdrant will serve stale vectors until the next full deploy.

---

## First Deploy

On the very first deploy, after the script runs:

1. Create the first superuser:
   ```bash
   ssh nexus-rag@72.62.196.231
   cd /home/nexus-rag/rag
   uv run python -m rag.scripts.create_superuser
   ```

2. Create the default tenant (workspace):
   ```bash
   curl -X POST https://chat.nexus.gayo-sphere.cloud/api/tenants \
     -H "Authorization: Bearer $JWT_TOKEN" \
     -d '{"name": "My Workspace", "slug": "my-workspace"}'
   ```

3. Verify ingest completed:
   ```bash
   curl https://chat.nexus.gayo-sphere.cloud/api/documents/index_summary \
     -H "Authorization: Bearer $JWT_TOKEN"
   ```

---

## systemd Unit

The service definition at `/etc/systemd/system/nexus-chat.service`:

```ini
[Unit]
Description=NEXUS RAG Chat Service
After=network.target postgresql.service

[Service]
Type=simple
User=nexus-rag
WorkingDirectory=/home/nexus-rag/rag
EnvironmentFile=/home/nexus-rag/.env
ExecStart=/home/nexus-rag/.local/bin/uv run uvicorn app:app \
    --host 127.0.0.1 \
    --port 8501 \
    --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable on first setup: `sudo systemctl enable nexus-chat`

---

## Rollback

`deploy-rag.sh` does not support automatic rollback. To rollback:

```bash
# On VPS: checkout previous git commit
cd /home/nexus-rag/rag
git log --oneline -5
git checkout <previous-commit>
uv sync
# If migration was applied, downgrade:
uv run alembic downgrade -1
sudo systemctl restart nexus-chat
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `rsync: permission denied` | SSH key not authorized | Add `~/.ssh/id_rsa.pub` to `~/.ssh/authorized_keys` on VPS |
| `alembic upgrade head` fails | Migration conflict | Check `alembic history`; resolve conflicts manually |
| Service fails to start | Config error in `.env` | `journalctl -u nexus-chat -n 50` to see startup errors |
| Smoke check returns `502` | uvicorn not yet ready | Wait 5s; retry curl |

---

## Related Docs

- [Alembic Migrations](alembic-migrations.md)
- [Post-Deploy Verification](post-deploy-verification.md)
- [Environment Setup](environment-setup.md)
