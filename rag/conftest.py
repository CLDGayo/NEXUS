"""Package-level pytest bootstrap.

Inject ``rag/`` onto ``sys.path`` so v1's flat imports (``from database
import …``, ``from routers import …``, ``from query import …``) resolve in
tests that boot ``rag.main:app`` — the messenger and orchestrator suites
now exercise the unified entrypoint after the Phase 9 cutover.

Production (Docker) sets ``PYTHONPATH=/app/rag`` in the Dockerfile, which
serves the same purpose at runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RAG_ROOT = Path(__file__).resolve().parent
if str(_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(_RAG_ROOT))

# Stub v1 env vars that ``query.py`` / ``ingest.py`` / ``inbox.py`` consume
# at module import time. Without these, importing ``rag.main`` from a test
# (which transitively imports v1 routers) raises ``KeyError`` before any
# test body runs. Production sets these via the env file mounted into the
# container; here we only need defaults that are syntactically valid.
os.environ.setdefault("VAULT_PATH", "/tmp/nexus-test-vault")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "")
os.environ.setdefault("QDRANT_COLLECTION", "nexus-vault-test")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-do-not-use-in-prod")
os.environ.setdefault("NEXUS_PASSWORD", "test-password")
os.environ.setdefault(
    "NEXUS_JWT_SECRET", "test-nexus-jwt-secret-32-bytes-minimum-XX"
)
