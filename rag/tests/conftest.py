"""Shared pytest fixtures for rag/ tests.

Sets the env vars that ``ingest`` and ``inbox`` read at import-time, so the
test process can import them without a live VAULT_PATH / Qdrant.
"""

import os
import sys
from pathlib import Path

# Make rag/ importable as the top-level package root (matches how the FastAPI
# app runs: `uvicorn app:app` from inside rag/).
RAG_ROOT = Path(__file__).resolve().parents[1]
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))


def pytest_configure(config):
    """Stub env vars early so import-time `os.environ[...]` reads succeed."""
    os.environ.setdefault("VAULT_PATH", "/tmp/nexus-test-vault")
    os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
    os.environ.setdefault("QDRANT_COLLECTION", "nexus-vault-test")
