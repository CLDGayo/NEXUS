"""Alembic environment for NEXUS Phase 27 IAM.

Pulls the DSN from ``rag.config.settings.postgres_dsn`` (NOT the static
``sqlalchemy.url`` placeholder in ``alembic.ini``) and wires
``target_metadata`` to ``rag.database.base.Base.metadata`` so autogenerate
sees the ``app.users`` / ``app.access_token`` / ``app.chat_sessions``
tables.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure env defaults exist before importing rag.config (Settings reads at
# import-time via pydantic). Real production deploys set these via env
# files; alembic CLI runs may be invoked with a bare shell.
os.environ.setdefault("VAULT_PATH", "/tmp/alembic-vault")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

from rag.config import settings  # noqa: E402
from rag.database.base import Base  # noqa: E402
from rag.database import models  # noqa: F401, E402  -- import side-effect registers tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the ini-level placeholder DSN with the real one from settings.
# Env override wins over settings so CI / tests can point at a sandbox DB.
runtime_dsn = os.environ.get("ALEMBIC_DSN") or settings.postgres_dsn
config.set_main_option("sqlalchemy.url", runtime_dsn)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):  # noqa: ANN001
    """Restrict autogenerate to the ``app`` schema only.

    LangGraph's ``langgraph_state`` schema is managed by
    ``AsyncPostgresSaver.setup()``; we must never drop/alter its tables.
    """
    if type_ == "table":
        schema = getattr(object, "schema", None)
        return schema == "app"
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        version_table_schema="app",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table_schema="app",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
