"""Phase 30.1 — conversations router unit contract.

The router was rewritten in Phase 30.1 to use SQLAlchemy 2.0 async ORM
against ``app.conversations`` / ``app.messages``. These tests assert the
shape of the route module (imports + handler signatures) without
standing up Postgres. End-to-end behaviour against a live database is
covered by the CI integration job.
"""

from __future__ import annotations

import inspect

import pytest


def test_router_uses_async_session_dependency() -> None:
    import typing

    from sqlalchemy.ext.asyncio import AsyncSession

    from rag.database.engine import get_async_session
    from rag.routers import conversations as module

    for name in (
        "list_conversations",
        "create_conversation",
        "get_conversation",
        "delete_conversation",
    ):
        fn = getattr(module, name)
        sig = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
        db_param = sig.parameters.get("db")
        assert db_param is not None, f"{name} must take ``db`` AsyncSession"
        assert hints.get("db") is AsyncSession, (
            f"{name} db param must be typed AsyncSession — got {hints.get('db')!r}"
        )
        default = db_param.default
        assert getattr(default, "dependency", None) is get_async_session, (
            f"{name} must Depend(get_async_session)"
        )


def test_module_does_not_import_aiosqlite() -> None:
    from rag.routers import conversations as module

    src = inspect.getsource(module)
    assert "aiosqlite" not in src, "Phase 30.1 ripped aiosqlite out"
    assert "DB_PATH" not in src, "DB_PATH was retired with the SQLite tables"


def test_handlers_carry_tenant_predicate() -> None:
    """Every route handler must filter by ``tenant.id`` so the same JWT
    against two different ``X-Tenant-ID`` headers yields disjoint reads."""
    from rag.routers import conversations as module

    src = inspect.getsource(module)
    assert "Conversation.tenant_id == tenant.id" in src
    assert "Conversation.user_id == user.id" in src


def test_path_params_are_uuid_typed() -> None:
    import typing
    import uuid

    from rag.routers import conversations as module

    for name in ("get_conversation", "delete_conversation"):
        fn = getattr(module, name)
        hints = typing.get_type_hints(fn)
        assert hints.get("conversation_id") is uuid.UUID, (
            f"{name} path param must be uuid.UUID — got {hints.get('conversation_id')!r}"
        )


def test_models_have_strict_fks() -> None:
    """Conversation + Message FKs must CASCADE on user/tenant delete."""
    from rag.database.models import Conversation, Message

    for model in (Conversation, Message):
        for fk_attr in ("user_id", "tenant_id"):
            col = model.__table__.c[fk_attr]
            fks = list(col.foreign_keys)
            assert fks, f"{model.__name__}.{fk_attr} must have an FK"
            assert fks[0].ondelete == "CASCADE", (
                f"{model.__name__}.{fk_attr} must CASCADE — got {fks[0].ondelete}"
            )

    msg_conv_fk = list(Message.__table__.c["conversation_id"].foreign_keys)
    assert msg_conv_fk and msg_conv_fk[0].ondelete == "CASCADE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
