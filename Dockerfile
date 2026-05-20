# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.5.11

WORKDIR /build
COPY requirements.txt requirements-ingest.txt ./
# Base runtime deps (api + outbound worker need only these).
RUN uv pip install --system --no-cache -r requirements.txt
# Ingest deps (transformers / torch CPU / docling / chonkie / sentence-transformers).
# Needed in this image because Step 4A runs `docker compose exec api python -m
# rag.ingest_v2 ingest --vault`. Image grows ~1 GB; acceptable for an ops box.
RUN uv pip install --system --no-cache \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-ingest.txt

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/rag

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r nexus --gid 1000 \
    && useradd -r -g nexus --uid 1000 --create-home --home-dir /home/nexus nexus

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY --chown=nexus:nexus rag /app/rag

USER nexus

EXPOSE 8000

# Phase 9 entry: unified Nexus API — v1 SPA / admin + v2 webhook + LangGraph
# cortex. v1's flat imports (e.g. ``from database import …``) resolve via
# ``PYTHONPATH=/app/rag`` set above. v1 ``rag/app.py`` is no longer the
# entry point and the legacy ``nexus-chat`` systemd unit is decommissioned
# as part of the cutover.
CMD ["uvicorn", "rag.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
