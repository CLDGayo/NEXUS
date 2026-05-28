"""Tests for ``rag/scripts/phase27_backfill.py``.

Phase 30.1 retired the ``DB_PATH`` constant the script imports from
``rag.database``. The legacy backfill is historical (already executed in
prod); the equivalent forward-looking transfer is now Alembic migration
``0004_phase30_sqlite_to_pg`` covered by
``test_phase30_migration_0004.py``.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 30.1: Phase 27 backfill script superseded by Alembic migration "
    "0004_phase30_sqlite_to_pg; tests retired.",
    allow_module_level=True,
)
