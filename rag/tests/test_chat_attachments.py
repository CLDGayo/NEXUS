"""Phase 15 — /api/chat/stream accepts attachments and threads them into
the graph state.

Phase 30.1 retired the aiosqlite ``database.init_db()`` bootstrap. The
chat stream contract is reasserted by the orchestrator smoke tests under
``rag/orchestrator/tests/`` and by the Playwright E2E suite.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: aiosqlite fixtures retired; orchestrator smoke + E2E "
    "cover this contract.",
    allow_module_level=True,
)
