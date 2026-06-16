# Deployment Issues

---

## Service Won't Start

```bash
# Check status
sudo systemctl status nexus-chat --no-pager

# Get startup errors
journalctl -u nexus-chat -n 100 --no-pager | grep -E "ERROR|CRITICAL|Traceback"
```

| Error in logs | Cause | Fix |
|---|---|---|
| `KeyError: 'GROQ_API_KEY'` | `.env` not loaded | Verify `EnvironmentFile=/home/nexus-rag/.env` in unit file; check file exists |
| `asyncpg.exceptions.InvalidAuthorizationSpecification` | Wrong DB password in `DATABASE_URL` | Fix `DATABASE_URL` in `.env`; restart |
| `Address already in use: port 8501` | Previous process still running | `sudo fuser -k 8501/tcp`; restart |
| `ModuleNotFoundError` | `uv sync` not run after deploy | `cd /home/nexus-rag/rag && uv sync`; restart |

---

## 502 Bad Gateway

nginx receives 502 when uvicorn is not responding.

```bash
# Is uvicorn running?
sudo systemctl is-active nexus-chat

# Is it listening on 8501?
ss -tlnp | grep 8501

# Check nginx error log
sudo tail -20 /var/log/nginx/error.log
```

Fix: `sudo systemctl restart nexus-chat`. If it keeps failing, check startup errors above.

---

## Migration Errors

```bash
cd /home/nexus-rag/rag
uv run alembic current     # Current revision
uv run alembic history     # Full history
```

| Error | Cause | Fix |
|---|---|---|
| `relation "app.X" does not exist` | Migration not applied | `uv run alembic upgrade head` |
| `Multiple head revisions` | Diverged migration tree | `uv run alembic merge heads -m "merge"`; upgrade |
| `Can't locate revision identifier` | Revision file deleted | Restore from git; or `alembic stamp head` if DB is correct |
| Migration hangs | Long-running table lock | Check `pg_stat_activity` for blocking queries; kill if safe |

---

## Docker Container Issues

```bash
# Check all containers
docker compose -f infra/docker-compose.yml ps

# Restart a failed container
docker compose -f infra/docker-compose.yml restart qdrant-nexus

# View container logs
docker compose -f infra/docker-compose.yml logs --tail=50 qdrant-nexus
```

| Container | Common failure | Fix |
|---|---|---|
| `qdrant-nexus` | Port 6333 in use | `lsof -i :6333`; kill conflicting process |
| `nexus-redis` | Data volume permission error | `chown -R 999:999 /var/lib/docker/volumes/redis-data` |
| `nexus-minio` | Bucket not created | Run `mc mb` bucket creation commands |

---

## fastembed Model Cache Issues

fastembed downloads ONNX models on first use. Disk full or cache corruption causes failures:

```bash
# Locate cache
find ~/.cache -name "*bge-small*" -type d 2>/dev/null
find ~/.cache -name "*ms-marco*" -type d 2>/dev/null

# Clear and re-download (service re-downloads on next start)
rm -rf ~/.cache/huggingface/hub/models--qdrant--bge-small-en-v1.5-onnx-q
```

> **📝 NOTE:** The on-disk cache path (`models--qdrant--bge-small-en-v1.5-onnx-q`) differs from the user-facing model ID (`BAAI/bge-small-en-v1.5`). Never predict the cache path from the model ID.

---

## Disk Full

```bash
df -h /home
# Check largest directories
du -sh /home/nexus-qdrant/storage/    # Vector data
du -sh /home/nexus-minio/data/        # Object storage
du -sh /home/nexus-rag/               # Application code + venv
```

Qdrant storage grows with vault size. Archive or delete old documents via `POST /api/documents/archive` before disk runs out.

---

## Related Docs

- [RAG Deployment](../12-deployment/rag-deployment.md)
- [Alembic Migrations](../12-deployment/alembic-migrations.md)
- [Docker Compose Guide](../12-deployment/docker-compose-guide.md)
- [Post-Deploy Verification](../12-deployment/post-deploy-verification.md)
