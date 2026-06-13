# Quickstart Guide

Get NEXUS running locally in under 10 minutes. This guide covers the minimum path from clone to first streaming chat response.

---

## Prerequisites

| Requirement | Minimum version | Install |
|---|---|---|
| Python | 3.11 | [python.org](https://python.org) |
| uv | latest | `pip install uv` or `brew install uv` |
| PostgreSQL | 14+ | `brew install postgresql` or Docker |
| Qdrant | 1.7+ | Docker (see Step 4) |
| Redis | 7+ | `brew install redis` or Docker |

> **📝 NOTE:** MinIO is optional for local development. Avatar and product image uploads will fail gracefully without it.

---

## Step 1 — Clone the Repository

```bash
git clone <your-repo-url> "Second Brain Nexus"
cd "Second Brain Nexus"
```

---

## Step 2 — Configure Environment Variables

Copy the example environment file and populate it with your credentials:

```bash
cp rag/.env.example rag/.env
```

Open `rag/.env` and set at minimum:

```bash
# Required for startup
POSTGRES_DSN=postgresql+asyncpg://user:password@localhost:5432/nexus
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=nexus-vault
REDIS_URL=redis://localhost:6379

# Required for LLM generation
GROQ_API_KEY=gsk_...

# Required for authentication
NEXUS_JWT_SECRET=your-32-char-minimum-secret-here

# Your local Obsidian vault path
VAULT_PATH=/Users/yourname/path/to/your/vault
```

→ See [Environment Variables Reference](../16-configuration-reference/environment-variables.md) for the complete list.

---

## Step 3 — Install Python Dependencies

NEXUS uses `uv` for fast, reproducible installs:

```bash
cd rag
uv sync
```

This installs all dependencies from `rag/uv.lock`, including FastAPI, LangGraph, Qdrant client, fastembed, and all retrieval components.

---

## Step 4 — Start Infrastructure (Docker Compose)

The quickest way to spin up Qdrant, Redis, and PostgreSQL:

```bash
# From repo root
docker compose -f docker-compose.dev.yml up -d
```

Verify all services are healthy:

```bash
docker compose ps
# qdrant: healthy
# redis:  healthy
# postgres: healthy
```

> **⚠️ WARNING:** The Qdrant container downloads the fastembed ONNX model on first startup (~40 MB). Ensure the Docker volume has enough space and allow ~60 seconds on first run.

---

## Step 5 — Run Database Migrations

Apply all Alembic migrations to create the PostgreSQL schema:

```bash
cd rag
uv run alembic upgrade head
```

Expected output:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, phase27_part1_users
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, phase29_multi_tenancy
...
INFO  [alembic.runtime.migration] Running upgrade 0009 -> 0010, phase52_wm3_lifecycle
```

→ See [Alembic Migrations Guide](../12-deployment/alembic-migrations.md) for details.

---

## Step 6 — Ingest Your Vault

Index your Obsidian vault into Qdrant + PostgreSQL:

```bash
cd rag
uv run python -m ingest_v2.pipeline --vault-path "$VAULT_PATH" --tenant-slug personal
```

For a large vault (500+ notes), this takes 2–10 minutes depending on hardware. Watch progress:

```bash
# In another terminal
uv run python -m ingest_v2.pipeline --vault-path "$VAULT_PATH" --verbose
```

> **💡 PRO TIP:** The file watcher (`rag/watcher.py`) keeps the index current after the initial ingest. Start it as a background process alongside the API:
> ```bash
> uv run python -m watcher &
> ```

---

## Step 7 — Start the API Server

```bash
cd rag
uv run uvicorn main:app --host 127.0.0.1 --port 8501 --reload
```

Verify the server is up:

```bash
curl -s http://localhost:8501/api/health | python -m json.tool
```

Expected response:

```json
{
  "status": "healthy",
  "components": {
    "qdrant": "ok",
    "postgres": "ok",
    "redis": "ok"
  }
}
```

---

## Step 8 — Build and Serve the Frontend

```bash
cd nexus-ui
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Step 9 — First Login

1. Navigate to `http://localhost:5173`
2. Click **Sign In**
3. Use the credentials you set in your `.env` (`NEXUS_ADMIN_EMAIL` / `NEXUS_ADMIN_PASSWORD`) or create a superuser:

```bash
cd rag
uv run python -c "
from auth.manager import create_superuser
import asyncio
asyncio.run(create_superuser('admin@example.com', 'your-password'))
"
```

---

## Step 10 — Send Your First Chat Message

**Via the UI:** Type a question in the chat input and press Enter. You should see the streaming response with `[n]` citations.

**Via the API directly:**

```bash
# Get a JWT token
TOKEN=$(curl -s -X POST http://localhost:8501/api/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=your-password" \
  | python -m json.tool | grep access_token | cut -d'"' -f4)

# Send a chat message
curl -N -X POST http://localhost:8501/api/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is NEXUS?", "session_id": "test-session-1"}'
```

You will see SSE events streaming:

```
data: {"type": "status", "content": "Searching knowledge base…"}
data: {"type": "sources", "sources": [...]}
data: {"type": "token", "content": "NEXUS"}
data: {"type": "token", "content": " is"}
...
data: {"type": "done"}
```

---

## Troubleshooting First Run

| Symptom | Likely cause | Fix |
|---|---|---|
| `Connection refused` on port 8501 | API server not started | Run `uv run uvicorn main:app --port 8501` |
| `qdrant: unhealthy` in `/api/health` | Qdrant container not running | `docker compose up -d qdrant` |
| Empty responses / no sources | Vault not ingested | Re-run Step 6 |
| `JWT decode error` | `NEXUS_JWT_SECRET` missing or wrong | Check `rag/.env` |
| `asyncpg cannot connect` | Postgres DSN wrong or DB not running | Verify `POSTGRES_DSN` + `docker compose up -d postgres` |

→ Full troubleshooting guide: [Troubleshooting Index](../17-troubleshooting/README.md)

---

## Next Steps

| Goal | Read next |
|---|---|
| Understand how answers are generated | [RAG Pipeline →](../02-rag-pipeline/README.md) |
| Set up multi-tenant workspaces | [Workspace Management →](../04-workspace-management/README.md) |
| Deploy to a VPS | [Deployment Guide →](../12-deployment/README.md) |
| Connect Meta Messenger | [Messenger Integration →](../07-messenger-integration/README.md) |
| Customize the AI persona | [AI Customization →](../06-ai-customization/README.md) |
