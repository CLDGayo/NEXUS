"""Phase 30.1 — settings_service rewritten to async ORM with JSONB values."""

from __future__ import annotations

import inspect

import pytest

from rag.database.models import Setting
from sqlalchemy.dialects.postgresql import JSONB


def test_settings_service_does_not_import_aiosqlite() -> None:
    import ast
    import rag.settings_service as module

    src = inspect.getsource(module)
    tree = ast.parse(src)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "aiosqlite" not in imports, (
        f"settings_service must not import aiosqlite — imports: {imports}"
    )
    # DB_PATH constant must not be referenced anywhere (function or arg).
    assert "DB_PATH" not in src.replace("DB_PATH``", "")


def test_setting_model_value_is_jsonb() -> None:
    value_col = Setting.__table__.c["value"]
    assert isinstance(value_col.type, JSONB)


def test_setting_pk_is_text_key() -> None:
    pk = list(Setting.__table__.primary_key.columns)
    assert len(pk) == 1 and pk[0].name == "key"


@pytest.mark.asyncio
async def test_unknown_key_raises_key_error() -> None:
    import rag.settings_service as module

    with pytest.raises(KeyError):
        await module.get("DOES_NOT_EXIST")
    with pytest.raises(KeyError):
        await module.set_value("DOES_NOT_EXIST", 1)


def test_describe_returns_allowed_keys_metadata() -> None:
    import rag.settings_service as module

    meta = module.describe()
    keys = {entry["key"] for entry in meta}
    assert "TOP_K" in keys and "GROQ_MODEL" in keys
