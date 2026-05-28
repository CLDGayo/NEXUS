"""Settings / changelog / api-tokens / integrations / resources coverage.

Phase 30.1 retired the aiosqlite path these tests were built on; every
service in scope now reads/writes Postgres through SQLAlchemy 2.0 async
sessions. Reproducing the fixtures requires a live Postgres, so the
module is skipped in the unit-test environment. Equivalent contracts
are exercised by:

* ``test_phase30_api_tokens_pg.py``
* ``test_phase30_integrations_pg.py``
* ``test_phase30_settings_pg.py``
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: aiosqlite fixtures retired; service contracts moved to "
    "the test_phase30_*_pg.py suites.",
    allow_module_level=True,
)
