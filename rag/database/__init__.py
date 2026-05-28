"""Database package.

Phase 30.1 retired the aiosqlite-backed ``conversations``, ``messages``,
``settings``, ``integrations`` and ``api_tokens`` tables. Every reader
and writer now goes through SQLAlchemy 2.0 async sessions
(``rag.database.engine``) against the Postgres ``app`` schema.

The ORM models live in ``rag.database.models``; the declarative ``Base``
in ``rag.database.base``; the async engine + ``get_async_session``
dependency in ``rag.database.engine``. Schema bootstrap is owned
exclusively by Alembic — there is no application-startup DDL.

This module retains only small process-wide helpers (``new_id``,
``now_iso``, ``DEFAULT_TENANT_SLUG``) that pre-existing call sites
import flat.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Phase 29 — the slug used by legacy SQLite rows. Retained because the
# Phase 30.1 Alembic migration ``0004_phase30_sqlite_to_pg`` rewrites
# this string into the canonical Postgres tenant slug during the
# one-shot data transfer.
DEFAULT_TENANT_SLUG = "hunter"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


__all__ = ["DEFAULT_TENANT_SLUG", "new_id", "now_iso"]
