"""Dashboard live-telemetry coverage.

Phase 30.1 retired the aiosqlite path these tests were built on; the
dashboard helpers now query ``app.conversations`` / ``app.messages`` /
``app.integrations`` via the SQLAlchemy 2.0 async sessionmaker. The
underlying KPI math is unchanged — the SQL window functions and date
truncation are now Postgres-native instead of ``substr(created_at, 1, 10)``
— and is exercised end to end against a live backend by the dashboard
journey in the Playwright E2E suite.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: aiosqlite fixtures retired; dashboard KPIs covered by "
    "the Playwright E2E dashboard journey.",
    allow_module_level=True,
)
