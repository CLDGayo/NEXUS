#!/bin/bash
# Deploy NEXUS RAG to VPS — syncs vault + rag code, restarts Chainlit
set -e

VAULT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VPS="root@72.62.196.231"
VPS_VAULT="/home/nexus-vault"
VPS_RAG="/home/nexus-rag"

echo "→ Syncing vault notes to VPS..."
rsync -avz --delete \
  --exclude='_publish/' \
  --exclude='.obsidian/' \
  --exclude='rag/' \
  --exclude='.git/' \
  "$VAULT_ROOT/" "$VPS:$VPS_VAULT/"

echo "→ Syncing rag/ code to VPS..."
rsync -avz --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.ingest_state.json' \
  "$VAULT_ROOT/rag/" "$VPS:$VPS_RAG/"

echo "→ Running ingestion pipeline on VPS..."
ssh "$VPS" "
  source /root/.local/bin/env
  cd $VPS_RAG
  uv run python ingest.py
"

echo "→ Restarting Chainlit service..."
ssh "$VPS" "systemctl restart nexus-chat && sleep 2 && systemctl is-active nexus-chat"

echo "Done. Chat at https://chat.nexus.gayo-sphere.cloud (once DNS + SSL are set up)"
