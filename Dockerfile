# syntax=docker/dockerfile:1.7

# ---------- Stage 0: UI builder ----------
# Compiles the React SPA (nexus-ui) into static assets. The runtime stage
# COPYs the produced dist/ folder into /app/nexus-ui/dist, which rag/main.py
# serves via FastAPI StaticFiles + a catch-all SPA route.
FROM node:22-alpine AS ui

WORKDIR /ui

# Cache npm install layer until lockfile changes.
COPY nexus-ui/package.json nexus-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY nexus-ui/ ./
RUN npm run build

# ---------- Stage 1: Python builder ----------
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

# Pre-create the cache tree so the nexus user owns ``~/.cache`` *before* the
# docker volume mount at ``~/.cache/fastembed``. Without this the implicit
# mkdir performed by the volume mount creates ``~/.cache`` as root, which
# blocks ``huggingface_hub`` and ``hf_xet`` from writing their own siblings
# (``~/.cache/huggingface/xet/logs``, ``hub/``, etc.) and surfaces as
# ``[I/O] Permission denied (os error 13)`` during model download.
RUN mkdir -p /home/nexus/.cache/fastembed /home/nexus/.cache/huggingface \
    && chown -R nexus:nexus /home/nexus/.cache

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY --chown=nexus:nexus rag /app/rag
COPY --chown=nexus:nexus docs /app/docs

# React SPA build — rag/main.py serves nexus-ui/dist/index.html + assets.
COPY --from=ui --chown=nexus:nexus /ui/dist /app/nexus-ui/dist

# Point HF + Xet caches at writable nexus-owned paths.
ENV HF_HOME=/home/nexus/.cache/huggingface \
    XDG_CACHE_HOME=/home/nexus/.cache

USER nexus

EXPOSE 8000

# Phase 9 entry: unified Nexus API — v1 SPA / admin + v2 webhook + LangGraph
# cortex. v1's flat imports (e.g. ``from database import …``) resolve via
# ``PYTHONPATH=/app/rag`` set above. v1 ``rag/app.py`` is no longer the
# entry point and the legacy ``nexus-chat`` systemd unit is decommissioned
# as part of the cutover. Phase 11 swapped the legacy rag/static/ SPA for
# the React build at /app/nexus-ui/dist (copied from stage `ui`).
#
# Phase 20: gate uvicorn behind ``rag.preflight_validator`` so the worker
# refuses to bind ``:8000`` until both FastEmbed ONNX models are verified
# on disk. ``exec`` hands uvicorn PID 1 so SIGTERM still propagates.
CMD ["sh", "-c", "python -m rag.preflight_validator && exec uvicorn rag.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
