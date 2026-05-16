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
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

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

# Phase 2 entry: the v2 Messenger webhook surface. v1 (`rag/app.py`) keeps
# running on the VPS systemd unit until the Phase 9 cutover; it is not
# imported by this container, so its flat imports are irrelevant here.
CMD ["uvicorn", "rag.messenger.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
