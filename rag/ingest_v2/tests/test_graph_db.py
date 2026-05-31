"""Tests for the Postgres-backed vault-link graph layer (Phase 31+).

Migration note (old → new API):
  - upsert_note(conn, path, title, aliases) was removed.
    Replacement: upsert_document(session, tenant_id=..., file=..., title=...,
                 aliases=(...)) which returns a UUID used by replace_links_for.
  - replace_links_for now takes src_document_id (UUID) not src_path.
  - all_links / fetch_note_titles / neighbors_of / resolve_link_targets all
    require tenant_id= keyword arg.
  - connect() yields an AsyncSession (SQLAlchemy); the session auto-commits
    on clean exit so manual conn.commit() calls are removed.
  - all_links rows now carry src_document_id / dst_document_id (UUID strings),
    not src_path / dst_path. Tests that formerly asserted on paths now assert
    on UUIDs or use fetch_note_titles to reverse-look-up.
  - The SQLite NEXUS_GRAPH_DB env-var fixture is gone; tests require a live
    Postgres connection and are skipped when DATABASE_URL is absent.
"""

from __future__ import annotations

import os
import uuid

import pytest

from rag.ingest_v2.graph_db import (
    all_links,
    connect,
    fetch_note_titles,
    neighbors_of,
    replace_links_for,
    resolve_link_targets,
    upsert_document,
)

# ---------------------------------------------------------------------------
# Skip whole module when no Postgres is configured.
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="Postgres DATABASE_URL not set — graph_db tests skipped",
)

# A stable tenant UUID per test run so rows don't bleed across tenants.
_TENANT = uuid.uuid4()


@pytest.mark.unit
@pytest.mark.asyncio
class TestSchema:
    async def test_connect_yields_session(self) -> None:
        """connect() must yield without error (schema already migrated)."""
        async with connect() as session:
            assert session is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestUpsertAndLinks:
    async def test_upsert_document_and_links(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            doc_id = await upsert_document(
                session,
                tenant_id=tenant,
                file="/vault/Projects/Alpha.md",
                title="Project Alpha",
                aliases=("Alpha", "PA"),
            )
            assert isinstance(doc_id, uuid.UUID)

            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=doc_id,
                links=(
                    ("Project Beta", None, None),
                    ("Project Beta", "Tasks", None),
                    ("Concept X", None, "the x note"),
                ),
            )

            links = await all_links(session, tenant_id=tenant)
            assert len(links) == 3

            titles = await fetch_note_titles(session, tenant_id=tenant)
            files = [row[0] for row in titles]
            assert "/vault/Projects/Alpha.md" in files
            # Aliases are preserved on the document row.
            alpha_row = next(r for r in titles if r[0] == "/vault/Projects/Alpha.md")
            assert set(alpha_row[2]) >= {"Alpha", "PA"}

    async def test_replace_overwrites(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            doc_id = await upsert_document(
                session, tenant_id=tenant, file="/v/a.md", title="A"
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=doc_id,
                links=(("B", None, None), ("C", None, None)),
            )
            # Overwrite with a single link.
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=doc_id,
                links=(("D", None, None),),
            )

            links = await all_links(session, tenant_id=tenant)
            targets = {lnk["dst_target"] for lnk in links}
            assert targets == {"D"}

    async def test_replace_dedups_duplicate_target_anchor(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            doc_id = await upsert_document(
                session, tenant_id=tenant, file="/v/a.md", title="A"
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=doc_id,
                links=(
                    ("B", "Section1", None),
                    ("B", "Section1", None),  # duplicate (target, anchor)
                    ("B", "Section2", None),  # different anchor → distinct row
                ),
            )

            links = await all_links(session, tenant_id=tenant)
            anchors = sorted(lnk["anchor"] for lnk in links)
            assert anchors == ["Section1", "Section2"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestResolveTargets:
    async def test_resolves_titles(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            id_a = await upsert_document(
                session, tenant_id=tenant, file="/v/A.md", title="A"
            )
            id_b = await upsert_document(
                session, tenant_id=tenant, file="/v/B.md", title="B"
            )
            id_c = await upsert_document(
                session, tenant_id=tenant, file="/v/C.md", title="C"
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_a,
                links=(("B", None, None), ("C", None, None)),
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_b,
                links=(("C", None, None),),
            )

        async with connect() as session:
            resolved = await resolve_link_targets(session, tenant_id=tenant)
            assert resolved == 3

            links = await all_links(session, tenant_id=tenant)
            # All three links should now have dst_document_id populated.
            resolved_ids = {lnk["dst_document_id"] for lnk in links}
            assert None not in resolved_ids
            assert str(id_b) in resolved_ids
            assert str(id_c) in resolved_ids

    async def test_resolves_aliases(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            id_alpha = await upsert_document(
                session,
                tenant_id=tenant,
                file="/v/Alpha.md",
                title="Project Alpha",
                aliases=("Alpha", "PA"),
            )
            id_beta = await upsert_document(
                session, tenant_id=tenant, file="/v/Beta.md", title="Project Beta",
                aliases=("PB",),
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_beta,
                links=(("PA", None, None),),  # alias of Alpha
            )

        async with connect() as session:
            await resolve_link_targets(session, tenant_id=tenant)
            links = await all_links(session, tenant_id=tenant)
            # The link from Beta → PA alias should resolve to Alpha's UUID.
            assert links[0]["dst_document_id"] == str(id_alpha)

    async def test_unresolved_stays_null(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            id_a = await upsert_document(
                session, tenant_id=tenant, file="/v/A.md", title="A"
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_a,
                links=(("Nonexistent", None, None),),
            )

        async with connect() as session:
            await resolve_link_targets(session, tenant_id=tenant)
            links = await all_links(session, tenant_id=tenant)
            assert links[0]["dst_document_id"] is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestNeighbors:
    async def test_one_hop_forward_and_reverse(self) -> None:
        tenant = uuid.uuid4()
        async with connect() as session:
            id_a = await upsert_document(
                session, tenant_id=tenant, file="/v/A.md", title="A"
            )
            id_b = await upsert_document(
                session, tenant_id=tenant, file="/v/B.md", title="B"
            )
            id_c = await upsert_document(
                session, tenant_id=tenant, file="/v/C.md", title="C"
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_a,
                links=(("B", None, None), ("C", None, None)),
            )
            await replace_links_for(
                session,
                tenant_id=tenant,
                src_document_id=id_b,
                links=(("C", None, None),),
            )
            await resolve_link_targets(session, tenant_id=tenant)

        async with connect() as session:
            # A → B, A → C, B → C.  Neighbors of C = {A, B} (both reverse).
            n_c = set(
                await neighbors_of(session, "/v/C.md", tenant_id=tenant)
            )
            assert n_c == {"/v/A.md", "/v/B.md"}

            # Neighbors of B = forward {C} + reverse {A}.
            n_b = set(
                await neighbors_of(session, "/v/B.md", tenant_id=tenant)
            )
            assert n_b == {"/v/A.md", "/v/C.md"}
