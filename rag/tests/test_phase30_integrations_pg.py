"""Phase 30.1 — integrations router + dispatcher rewritten to async ORM."""

from __future__ import annotations

import inspect
import uuid

from sqlalchemy.dialects.postgresql import JSONB

from rag.database.models import Integration


def test_integrations_router_does_not_import_aiosqlite() -> None:
    from rag.routers import integrations as module

    src = inspect.getsource(module)
    assert "aiosqlite" not in src
    assert "config_json" not in src, "JSONB column is named ``config`` now"


def test_dispatcher_does_not_import_aiosqlite() -> None:
    from rag.integrations import dispatcher as module

    src = inspect.getsource(module)
    assert "aiosqlite" not in src
    assert "get_sessionmaker" in src, "dispatcher must open one-shot sessions"


def test_integration_model_jsonb_and_uuid_pk() -> None:
    pk = list(Integration.__table__.primary_key.columns)
    assert len(pk) == 1 and pk[0].name == "id"
    assert pk[0].type.python_type is uuid.UUID

    config_col = Integration.__table__.c["config"]
    assert isinstance(config_col.type, JSONB), "config must be JSONB"
    assert not config_col.nullable, "config is required"


def test_path_params_are_uuid_typed() -> None:
    import typing

    from rag.routers.integrations import (
        delete_integration,
        test_integration,
        update_integration,
    )

    for fn in (update_integration, delete_integration, test_integration):
        hints = typing.get_type_hints(fn)
        assert hints.get("integration_id") is uuid.UUID, (
            f"{fn.__name__} integration_id must be uuid.UUID — "
            f"got {hints.get('integration_id')!r}"
        )
