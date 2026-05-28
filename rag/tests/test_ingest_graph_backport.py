"""Phase 23 — v1 ingest graph backport.

Phase 31 retired the aiosqlite-backed ``nexus_graph.db`` these tests
were written against. The v1 ``_index_graph_for_files`` now writes to
``app.documents`` and ``app.document_links`` and requires a live Postgres
plus a pre-provisioned tenant row. The integration suite covers that
end-to-end; the unit-test environment skips the module to keep the suite
green.

Behaviour preserved (and exercised at the SQL layer):
    * ``rag/ingest.py::_index_graph_for_files`` upserts one Document per
      ingested file and replaces its outbound link rows for the active
      tenant.
    * ``rag.ingest_v2.graph_db.neighbors_of`` returns both forward and
      reverse edges scoped to the tenant.

Verified by ``test_phase31_graph_tenancy.py`` (signature shape) and the
integration tests that hit a real Postgres in CI.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Phase 31: aiosqlite-backed graph DB retired; tenancy + persistence "
    "are now covered by test_phase31_graph_tenancy.py against the Postgres "
    "Document model, and by the integration suite end-to-end.",
    allow_module_level=True,
)
