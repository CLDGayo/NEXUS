"""Phase 30.1 — api_tokens router rewritten to async ORM."""

from __future__ import annotations

import inspect
import uuid

import pytest

from rag.database.models import ApiToken


def test_module_does_not_import_aiosqlite() -> None:
    from rag.routers import api_tokens as module

    src = inspect.getsource(module)
    assert "aiosqlite" not in src
    assert "DB_PATH" not in src


def test_token_model_has_uuid_pk_and_unique_hash() -> None:
    pk_cols = [c for c in ApiToken.__table__.primary_key.columns]
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "id"
    assert pk_cols[0].type.python_type is uuid.UUID

    token_hash = ApiToken.__table__.c["token_hash"]
    assert token_hash.unique, "token_hash must be unique"


def test_revoke_path_param_is_uuid() -> None:
    import typing

    from rag.routers.api_tokens import revoke_token

    hints = typing.get_type_hints(revoke_token)
    assert hints.get("token_id") is uuid.UUID


def test_lookup_token_dep_uses_sessionmaker() -> None:
    from rag.routers import deps as module

    src = inspect.getsource(module)
    assert "get_sessionmaker" in src
    assert "aiosqlite" not in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
