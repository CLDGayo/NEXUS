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

echo "→ Syncing rag/ code to $VPS:$VPS_PROJECT/rag ..."
rsync -avz --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.ingest_state.json' \
  --exclude='data/.password_override.json' \
  --exclude='data/nexus.db' \
  --exclude='data/traces/' \
  --exclude='data/app.log' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='auth/' \
  "$VAULT_ROOT/rag/" "$VPS:$VPS_PROJECT/rag/"

echo "→ Syncing project root infra files (Dockerfile, compose, requirements) ..."
rsync -avz \
  "$VAULT_ROOT/Dockerfile" \
  "$VAULT_ROOT/docker-compose.yml" \
  "$VAULT_ROOT/docker-compose.prod.yml" \
  "$VAULT_ROOT/docker-compose.lite.yml" \
  "$VAULT_ROOT/requirements.txt" \
  "$VAULT_ROOT/requirements-ingest.txt" \
  "$VPS:$VPS_PROJECT/"

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

echo "→ Smoke-test public endpoints ..."
curl -sS -o /dev/null -w "  GET  /health                 : HTTP %{http_code}\n" \
  https://chat.nexus.gayo-sphere.cloud/health
curl -sS -o /dev/null -w "  POST /api/auth/login (wrong) : HTTP %{http_code}\n" \
  -X POST https://chat.nexus.gayo-sphere.cloud/api/auth/login \
  -H 'content-type: application/json' -d '{"password":"__smoke__"}'

echo "Done. App at https://chat.nexus.gayo-sphere.cloud"
