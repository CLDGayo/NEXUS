#!/bin/bash
set -e

VAULT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VPS_USER="root"
VPS_HOST="72.62.196.231"
VPS_DEST="/home/gayo-sphere-nexus/htdocs/nexus.gayo-sphere.cloud"

echo "Building NEXUS..."
source ~/.nvm/nvm.sh 2>/dev/null || true
cd "$VAULT_ROOT/_publish"
npx quartz build -d ../ --output public

echo "Syncing to VPS..."
rsync -avz --delete public/ "$VPS_USER@$VPS_HOST:$VPS_DEST/"

echo "Fixing permissions on VPS..."
ssh "$VPS_USER@$VPS_HOST" "chown -R gayo-sphere-nexus:gayo-sphere-nexus $VPS_DEST"

echo "Done. Live at https://nexus.gayo-sphere.cloud"
