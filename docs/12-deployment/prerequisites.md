# Prerequisites

Everything that must exist before running `deploy-rag.sh` or `deploy-nexus.sh`.

---

## VPS Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD | 80 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Outbound internet | Required | Required |

> **📝 NOTE:** The fastembed ONNX models (~100 MB each) and Qdrant vector storage grow over time. Provision disk generously.

---

## DNS Records

| Subdomain | Type | Points to | Purpose |
|---|---|---|---|
| `chat.nexus.gayo-sphere.cloud` | A | VPS IP | RAG chat application |
| `nexus.gayo-sphere.cloud` | A/CNAME | CDN or VPS | Quartz vault site |
| `qdrant.nexus.gayo-sphere.cloud` | A | VPS IP | Qdrant public HTTPS (Mac dev access) |
| `assets.nexus.gayo-sphere.cloud` | A/CNAME | VPS or CDN | MinIO public assets |

---

## Required Software (VPS)

| Software | Version | Purpose |
|---|---|---|
| Docker | 24+ | Container runtime |
| Docker Compose | v2+ | Multi-container orchestration |
| Python | 3.11+ | RAG application runtime |
| uv | latest | Python package manager |
| Node.js | 22+ (nvm) | Quartz publishing |
| PostgreSQL | 15+ | Relational database |
| nginx | 1.24+ | Reverse proxy |
| rsync | 3.x | Deploy script file sync |

Install uv on VPS:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install Node 22 via nvm:
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install 22 && nvm use 22
```

---

## Required Software (Mac Dev)

| Software | Purpose |
|---|---|
| `uv` | Run `rag/` locally |
| Docker Desktop | Run infrastructure containers |
| Node.js 22 | Quartz local build |
| `ngrok` | Expose local webhook for Messenger dev testing |

---

## External Services

| Service | Required for | Config |
|---|---|---|
| Groq API | LLM generation | `GROQ_API_KEY` |
| Meta Developer App | Messenger integration | `MESSENGER_*` vars |
| Stripe (via n8n) | Checkout links | `N8N_WEBHOOK_CHECKOUT_URL` |
| GoHighLevel CRM (via n8n) | Lead capture | `N8N_WEBHOOK_LEAD_URL` |
| n8n | Webhook automation | Self-hosted or n8n.cloud |

---

## VPS System User

The application runs as a dedicated system user:

```bash
# Create user
sudo useradd -r -s /bin/bash -d /home/nexus-rag nexus-rag
sudo mkdir -p /home/nexus-rag
sudo chown nexus-rag:nexus-rag /home/nexus-rag
```

The systemd unit runs as `nexus-rag`. Deploy scripts `rsync` code to `/home/nexus-rag/`.

---

## PostgreSQL Setup

```bash
# Create database and user
sudo -u postgres psql
CREATE DATABASE nexus_rag;
CREATE USER nexus_rag WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE nexus_rag TO nexus_rag;
\q
```

Set `DATABASE_URL=postgresql+asyncpg://nexus_rag:password@localhost:5432/nexus_rag` in `.env`.

---

## Related Docs

- [Environment Setup](environment-setup.md) — `.env` file structure
- [Docker Compose Guide](docker-compose-guide.md) — infrastructure containers
- [RAG Deployment](rag-deployment.md) — first deploy walkthrough
