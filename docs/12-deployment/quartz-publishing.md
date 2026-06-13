# Quartz Publishing

`deploy-nexus.sh` builds the Quartz v4 static site from the Obsidian vault and deploys it to `nexus.gayo-sphere.cloud`.

---

## What the Script Does

```bash
./deploy-nexus.sh
```

1. Switches to Node 22 via nvm
2. `cd _publish && npm install` — install Quartz dependencies
3. `npx quartz build` — build static site from vault markdown into `_publish/public/`
4. `rsync` built files to VPS web root
5. Set correct file permissions

---

## Script Internals

```bash
#!/usr/bin/env bash
set -euo pipefail

VPS_USER="nexus-rag"
VPS_HOST="72.62.196.231"
VPS_WEB="/var/www/nexus.gayo-sphere.cloud/public"

echo "==> Using Node 22..."
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 22

echo "==> Building Quartz..."
cd _publish
npm install
npx quartz build

echo "==> Deploying to VPS..."
rsync -avz --delete public/ "$VPS_USER@$VPS_HOST:$VPS_WEB/"

echo "==> Setting permissions..."
ssh "$VPS_USER@$VPS_HOST" "chmod -R 755 $VPS_WEB"

echo "Deploy complete: https://nexus.gayo-sphere.cloud"
```

---

## Quartz Configuration

`_publish/quartz.config.ts` controls site behavior:

| Setting | Location | Purpose |
|---|---|---|
| `pageTitle` | `quartz.config.ts` | Site header title |
| `baseUrl` | `quartz.config.ts` | Must match `nexus.gayo-sphere.cloud` |
| `ignorePatterns` | `quartz.config.ts` | Exclude process/, .claude/, raw assets |
| `theme` | `quartz.config.ts` | Color scheme, font |

Key ignore patterns to keep private content out of the public site:

```typescript
ignorePatterns: [
  "process/**",
  ".claude/**",
  ".codex/**",
  "rag/**",
  "infra/**",
  "**/.env",
  "**/private/**"
]
```

---

## Local Preview

Before deploying, preview the site locally:

```bash
cd _publish
nvm use 22
npx quartz build --serve
# Opens at http://localhost:8080
```

---

## Node Version Requirement

Quartz v4 requires **Node ≥22**. It uses ESM modules that are incompatible with Node 18 and below. Always verify:

```bash
node --version  # Must be 22.x.x or higher
```

---

## Nginx Serving

On the VPS, nginx serves the static files directly:

```nginx
server {
    listen 443 ssl;
    server_name nexus.gayo-sphere.cloud;

    root /var/www/nexus.gayo-sphere.cloud/public;
    index index.html;

    location / {
        try_files $uri $uri/ $uri.html =404;
    }
}
```

No application server needed — pure static file serving.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails with ESM errors | Wrong Node version | `nvm use 22` before building |
| Pages not updating after deploy | Browser cache | Hard-refresh (`Cmd+Shift+R`) |
| Private notes appearing on site | `ignorePatterns` incomplete | Add path to `quartz.config.ts` ignorePatterns; rebuild |
| `rsync: No such file or directory` | VPS web root doesn't exist | `ssh nexus-rag@VPS mkdir -p /var/www/nexus.gayo-sphere.cloud/public` |

---

## Related Docs

- [Prerequisites](prerequisites.md) — Node 22 via nvm
- [nginx Configuration](nginx-configuration.md)
- [Post-Deploy Verification](post-deploy-verification.md)
