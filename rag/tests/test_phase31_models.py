"""Phase 31 — ORM shape: tenant_id on tokens/integrations + Document tables."""

from __future__ import annotations

import uuid

from rag.database.models import ApiToken, Document, DocumentLink, Integration


def test_api_token_has_tenant_id_fk_not_null() -> None:
    col = ApiToken.__table__.c["tenant_id"]
    assert col.nullable is False, "ApiToken.tenant_id must be NOT NULL"
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.fullname == "app.tenants"
    assert fks[0].ondelete == "CASCADE"


def test_integration_has_tenant_id_fk_not_null() -> None:
    col = Integration.__table__.c["tenant_id"]
    assert col.nullable is False, "Integration.tenant_id must be NOT NULL"
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.fullname == "app.tenants"
    assert fks[0].ondelete == "CASCADE"


def test_document_model_columns() -> None:
    cols = {c.name for c in Document.__table__.c}
    expected = {
        "id",
        "tenant_id",
        "file",
        "title",
        "folder",
        "tags",
        "aliases",
        "source_kind",
        "content_hash",
        "chunk_total",
        "modified_at",
        "indexed_at",
        "archived_at",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"

    tid = Document.__table__.c["tenant_id"]
    assert tid.nullable is False
    assert tid.type.python_type is uuid.UUID

    fks = list(tid.foreign_keys)
    assert fks and fks[0].column.table.fullname == "app.tenants"
    assert fks[0].ondelete == "CASCADE"


def test_document_unique_constraint_tenant_file() -> None:
    constraints = [
        c.name for c in Document.__table__.constraints if c.name
    ]
    assert "uq_app_documents_tenant_file" in constraints


def test_document_link_model_columns_and_fks() -> None:
    cols = {c.name for c in DocumentLink.__table__.c}
    expected = {
        "id",
        "tenant_id",
        "src_document_id",
        "dst_target",
        "dst_document_id",
        "anchor",
        "alias",
        "created_at",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"

    tid = DocumentLink.__table__.c["tenant_id"]
    assert tid.nullable is False

    src_fk = list(DocumentLink.__table__.c["src_document_id"].foreign_keys)
    assert src_fk and src_fk[0].column.table.fullname == "app.documents"
    assert src_fk[0].ondelete == "CASCADE"

    dst_fk = list(DocumentLink.__table__.c["dst_document_id"].foreign_keys)
    assert dst_fk and dst_fk[0].ondelete == "SET NULL"
