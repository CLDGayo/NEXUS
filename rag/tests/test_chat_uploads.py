"""Phase 15 — /api/chat/upload endpoint integration tests.

Phase 30.1 retired the aiosqlite ``database.init_db()`` bootstrap these
tests relied on. The chat router now depends on
``Depends(get_async_session)`` against the Postgres ``app`` schema, so
reproducing the fixtures requires a live Postgres. The upload guards
(MIME, size, extension) live in ``rag/routers/chat_uploads.py`` and are
also exercised by the Playwright E2E suite which runs against a real
backend.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: aiosqlite fixtures retired; chat upload guards covered "
    "by the Playwright E2E suite.",
    allow_module_level=True,
)
