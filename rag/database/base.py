"""SQLAlchemy declarative base pinned to the Postgres ``app`` schema.

Every ORM table inheriting from ``Base`` lands in ``app.<tablename>``.
``langgraph_state`` is owned by ``AsyncPostgresSaver.setup()`` and stays
out of scope for our migrations.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(schema="app")
