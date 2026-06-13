# Docker Compose Guide

Docker Compose manages the four infrastructure services: Qdrant, Redis, MinIO, and LiteLLM. The FastAPI application runs outside Docker under systemd.

---

## Compose File Location

```
infra/docker-compose.yml   # Primary compose file
```

---

## Services

### `qdrant-nexus`

```yaml
qdrant-nexus:
  image: qdrant/qdrant:latest
  container_name: qdrant-nexus
  ports:
    - "6333:6333"
    - "6334:6334"   # gRPC
  volumes:
    - /home/nexus-qdrant/storage:/qdrant/storage
  restart: always
```

**Data volume:** `/home/nexus-qdrant/storage/` — persists vectors across container restarts. Back this up before upgrades.

---

### `redis`

```yaml
redis:
  image: redis:7-alpine
  container_name: nexus-redis
  ports:
    - "6379:6379"
  volumes:
    - redis-data:/data
  restart: always
  command: redis-server --appendonly yes
```

`appendonly yes` enables AOF persistence. Redis data survives container restarts.

---

### `minio`

```yaml
minio:
  image: minio/minio:latest
  container_name: nexus-minio
  ports:
    - "9000:9000"   # API
    - "9001:9001"   # Console
  volumes:
    - /home/nexus-minio/data:/data
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
  command: server /data --console-address ":9001"
  restart: always
```

**Console:** `http://localhost:9001` (admin UI for bucket management).

**Create buckets on first run:**

```bash
docker exec nexus-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec nexus-minio mc mb local/nexus-avatars
```

---

### `litellm`

```yaml
litellm:
  image: ghcr.io/berriai/litellm:main-latest
  container_name: nexus-litellm
  ports:
    - "4000:4000"
  volumes:
    - ./litellm/config.yaml:/app/config.yaml
  command: --config /app/config.yaml --port 4000
  restart: always
```

LiteLLM acts as a model proxy, enabling fallback routing and API key normalization. Optional — the RAG app can call Groq directly without it.

---

## Operations

### Start all services

```bash
cd infra
docker compose up -d
```

### Check status

```bash
docker compose ps
```

### View logs

```bash
docker compose logs -f qdrant-nexus
docker compose logs -f nexus-redis
```

### Stop all

```bash
docker compose down
```

### Restart a single service

```bash
docker compose restart qdrant-nexus
```

---

## Data Volumes

| Service | Host path | Purpose |
|---|---|---|
| Qdrant | `/home/nexus-qdrant/storage/` | Vector index + segments |
| Redis | `redis-data` (named volume) | AOF journal |
| MinIO | `/home/nexus-minio/data/` | Object blobs |

> **⚠️ WARNING:** Deleting Qdrant's host volume destroys all vector data. A full re-ingest is required to recover. Back up `/home/nexus-qdrant/storage/` before Qdrant upgrades.

---

## Networking

All containers are on the default Docker bridge network. The FastAPI application (running on the host as systemd) reaches containers via `localhost:{port}`:

| Service | Host-accessible at |
|---|---|
| Qdrant | `http://127.0.0.1:6333` |
| Redis | `redis://127.0.0.1:6379` |
| MinIO | `http://127.0.0.1:9000` |
| LiteLLM | `http://127.0.0.1:4000` |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Qdrant container not starting | Port 6333 already in use | `lsof -i :6333`; stop conflicting process |
| Redis data lost after restart | AOF not enabled | Add `--appendonly yes` to command |
| MinIO bucket missing | First run, bucket not created | Run `mc mb` commands above |
| LiteLLM not routing to Groq | `config.yaml` missing or wrong key | Check `litellm/config.yaml`; verify `GROQ_API_KEY` |

---

## Related Docs

- [Prerequisites](prerequisites.md)
- [RAG Deployment](rag-deployment.md)
- [Environment Setup](environment-setup.md)
