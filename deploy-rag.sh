#!/bin/bash
# Deploy NEXUS RAG to VPS — Phase 9 / v2 Docker architecture.
#
# Syncs the vault + project root (rag/, Dockerfile, compose files,
# requirements) to /home/nexus-rag-v2 on the VPS, then rebuilds the
# `api` service via docker compose. The legacy systemd unit
# (`nexus-chat`) and /home/nexus-rag tree are decommissioned and not
# touched here.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VPS="root@72.62.196.231"
VPS_VAULT="/home/nexus-vault"
VPS_PROJECT="/home/nexus-rag-v2"

echo "→ Syncing vault notes to $VPS:$VPS_VAULT ..."
rsync -avz --delete \
  --exclude='_publish/' \
  --exclude='.obsidian/' \
  --exclude='rag/' \
  --exclude='nexus-ui/' \
  --exclude='.git/' \
  "$VAULT_ROOT/" "$VPS:$VPS_VAULT/"

# The Docker api container runs as nexus (UID 1000). rsync copies files
# with the local macOS UID (501), so 00 - Inbox/ must be re-owned so the
# upload endpoint (routers/uploads.py → inbox.write_note_at) can write.
echo "→ Fixing ownership on 00 - Inbox/ and 04 - Archive/ for Docker nexus user ..."
ssh "$VPS" "mkdir -p '$VPS_VAULT/00 - Inbox' '$VPS_VAULT/04 - Archive' && chown -R 1000:1000 '$VPS_VAULT/00 - Inbox' '$VPS_VAULT/04 - Archive'"

echo "→ Syncing rag/ code to $VPS:$VPS_PROJECT/rag ..."
rsync -avz --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.ingest_state.json' \
  --exclude='data/.password_override.json' \
  --exclude='data/.messenger_override.json' \
  --exclude='data/nexus.db' \
  --exclude='data/traces/' \
  --exclude='data/app.log' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  "$VAULT_ROOT/rag/" "$VPS:$VPS_PROJECT/rag/"

echo "→ Syncing nexus-ui/ source for Docker UI builder stage ..."
rsync -avz --delete \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='.vite/' \
  "$VAULT_ROOT/nexus-ui/" "$VPS:$VPS_PROJECT/nexus-ui/"

echo "→ Syncing litellm/ config (mounted into the litellm container) ..."
rsync -avz --delete \
  "$VAULT_ROOT/litellm/" "$VPS:$VPS_PROJECT/litellm/"

echo "→ Syncing project root infra files (Dockerfile, compose, requirements, dockerignore) ..."
rsync -avz \
  "$VAULT_ROOT/Dockerfile" \
  "$VAULT_ROOT/.dockerignore" \
  "$VAULT_ROOT/docker-compose.yml" \
  "$VAULT_ROOT/docker-compose.prod.yml" \
  "$VAULT_ROOT/docker-compose.lite.yml" \
  "$VAULT_ROOT/requirements.txt" \
  "$VAULT_ROOT/requirements-ingest.txt" \
  "$VPS:$VPS_PROJECT/"

echo "→ Restarting litellm container so the new config.yaml is loaded ..."
ssh "$VPS" "
  set -e
  cd $VPS_PROJECT
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
                 --env-file .env.prod restart litellm
"

# Docker creates named volumes owned by root, but the api container runs as
# the nexus user (UID/GID 1000). Without this fix, FastEmbed fails with
# [Errno 13] Permission denied when downloading ms-marco / bge-small models
# into /home/nexus/.cache/fastembed, breaking reranker + ingest.
echo "→ Ensuring fastembed cache volume is writable by nexus (UID 1000) ..."
ssh "$VPS" "
  set -e
  docker volume create nexus_fastembed_cache >/dev/null
  docker run --rm -v nexus_fastembed_cache:/cache alpine:3.20 \
    chown -R 1000:1000 /cache
"

echo "→ Rebuilding api container via docker compose ..."
ssh "$VPS" "
  set -e
  cd $VPS_PROJECT
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
                 --env-file .env.prod up -d --build api
"

echo "→ Waiting for api to report healthy ..."
ssh "$VPS" '
  for i in $(seq 1 30); do
    status=$(docker inspect --format "{{.State.Health.Status}}" nexus-api 2>/dev/null || echo unknown)
    if [ "$status" = "healthy" ]; then
      echo "  api is healthy"
      exit 0
    fi
    sleep 2
  done
  echo "  api did not reach healthy state within 60s"
  docker logs nexus-api --tail 50
  exit 1
'

# Phase 27 — apply IAM migrations against the live Postgres. Runs inside
# the api container so the env (POSTGRES_DSN, NEXUS_JWT_SECRET) and the
# alembic.ini at /app/rag/alembic.ini are picked up exactly as the app
# sees them. Idempotent: alembic upgrade head is a no-op after first run.
echo "→ Applying Phase 27 Alembic migrations (app.users, app.access_token, app.chat_sessions) ..."
ssh "$VPS" "
  set -e
  docker exec -w /app/rag nexus-api alembic upgrade head
"

echo "→ Smoke-test public endpoints ..."
HOST="https://chat.nexus.gayo-sphere.cloud"
curl -sS -o /dev/null -w "  GET  /health                 : HTTP %{http_code}\n" "$HOST/health"
curl -sS -o /dev/null -w "  GET  /                       : HTTP %{http_code}  (React index)\n" "$HOST/"
curl -sS -o /dev/null -w "  GET  /documents              : HTTP %{http_code}  (SPA catch-all)\n" "$HOST/documents"
curl -sS -o /dev/null -w "  GET  /integrations           : HTTP %{http_code}  (SPA catch-all)\n" "$HOST/integrations"
curl -sS -o /dev/null -w "  POST /api/auth/login (wrong) : HTTP %{http_code}\n" \
  -X POST "$HOST/api/auth/login" \
  -H 'content-type: application/json' -d '{"password":"__smoke__"}'

# Confirm the hashed Vite entry bundle is served — parse <script src="/assets/...">
echo "→ Verifying Vite bundle URL ..."
asset=$(curl -sS "$HOST/" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)
if [ -n "$asset" ]; then
  curl -sS -o /dev/null -w "  GET  $asset : HTTP %{http_code}\n" "$HOST$asset"
else
  echo "  (could not detect hashed bundle path — check /)"
fi

echo "Done. App at $HOST"
