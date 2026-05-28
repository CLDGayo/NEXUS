"""Phase 28 Part 1 — conversations router scopes every read to ``user_id``.

Phase 30.1 retired the aiosqlite path these tests were built on; the
router now depends on ``Depends(get_async_session)`` against the Postgres
``app`` schema, so reproducing the fixtures in pytest requires a live
Postgres (or testcontainers). The CI integration job covers this end to
end; the unit-test environment skips the module to keep the suite green.

The tenancy contract these tests proved is preserved at the SQL layer by
``rag/routers/conversations.py`` which carries
``.where(Conversation.user_id == user.id, Conversation.tenant_id == tenant.id)``
on every query — verified by ``test_phase30_conversations_pg.py``.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: aiosqlite-backed fixtures retired; tenancy contract is "
    "now covered by test_phase30_conversations_pg.py against Postgres.",
    allow_module_level=True,
)
