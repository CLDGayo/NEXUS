"""Phase 27 Part 2 — one-off SQLite history backfill.

Adds the ``user_id TEXT`` column to the legacy v1 tables (``conversations``,
``messages``, ``api_tokens``) and stamps every existing row with the
designated superuser's UUID from ``app.users``. Safe to re-run: each table is
checked with ``PRAGMA table_info`` before the ``ALTER TABLE`` and the
``UPDATE`` only touches rows where ``user_id IS NULL``.

Usage::

    uv run python -m rag.scripts.phase27_backfill            # defaults
    uv run python -m rag.scripts.phase27_backfill --dry-run  # preview only
    uv run python -m rag.scripts.phase27_backfill --email other@nexus.test
    uv run python -m rag.scripts.phase27_backfill --db-path /tmp/x.db
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

import aiosqlite
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from rag.database import DB_PATH
from rag.database.engine import dispose_engine, get_sessionmaker
from rag.database.models import User

DEFAULT_SUPERUSER_EMAIL = "clarence@gayo-sphere.cloud"
TARGET_TABLES: tuple[str, ...] = ("conversations", "messages", "api_tokens")
INDEXED_TABLES: frozenset[str] = frozenset({"conversations", "messages"})

logger = logging.getLogger("rag.scripts.phase27_backfill")


@dataclass(frozen=True)
class TableReport:
    table: str
    added_column: bool
    rows_updated: int
    indexed: bool


async def _fetch_superuser_id(email: str) -> str:
    """Look up the superuser UUID by email; raise if missing or not a superuser."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        stmt = (
            select(User)
            .where(User.email == email)
            .where(User.is_superuser.is_(True))
            .where(User.is_active.is_(True))
            .limit(1)
        )
        try:
            result = await session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "Auth database unreachable — confirm Postgres + run "
                "`alembic upgrade head` before retrying."
            ) from exc
        user = result.scalar_one_or_none()
    if user is None:
        raise RuntimeError(
            f"No active superuser with email '{email}' in app.users. "
            "Register the account via POST /api/auth/register, then UPDATE "
            "app.users SET is_superuser = true WHERE email = '...'."
        )
    return str(user.id)


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        rows = await cur.fetchall()
    return any(row[1] == column for row in rows)


async def _backfill_table(
    db: aiosqlite.Connection,
    table: str,
    user_id: str,
    *,
    dry_run: bool,
) -> TableReport:
    column_exists = await _column_exists(db, table, "user_id")
    added = not column_exists
    if added:
        if dry_run:
            logger.info("[dry-run] would ALTER TABLE %s ADD COLUMN user_id TEXT", table)
        else:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")

    # Count what the real run would touch. If the column doesn't exist yet
    # (dry-run on a legacy DB), every row is pending — selecting WHERE
    # user_id IS NULL would raise OperationalError since the column is absent.
    if column_exists:
        count_sql = f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL"
    else:
        count_sql = f"SELECT COUNT(*) FROM {table}"
    async with db.execute(count_sql) as cur:
        row = await cur.fetchone()
    pending = int(row[0]) if row else 0

    if not dry_run and pending:
        await db.execute(
            f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )

    indexed = False
    if table in INDEXED_TABLES:
        idx = f"idx_{table}_user_id"
        if dry_run:
            logger.info("[dry-run] would CREATE INDEX IF NOT EXISTS %s ON %s(user_id)", idx, table)
        else:
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS {idx} ON {table}(user_id)"
            )
        indexed = True

    return TableReport(
        table=table,
        added_column=added,
        rows_updated=pending,
        indexed=indexed,
    )


async def run(*, email: str, db_path: str, dry_run: bool) -> list[TableReport]:
    """Execute the backfill end-to-end. Returns one report per table."""
    logger.info(
        "phase27 backfill start: email=%s db_path=%s dry_run=%s",
        email,
        db_path,
        dry_run,
    )

    try:
        user_id = await _fetch_superuser_id(email)
    finally:
        # Always release the asyncpg pool — script is short-lived.
        await dispose_engine()

    logger.info("resolved superuser uuid=%s", user_id)

    reports: list[TableReport] = []
    async with aiosqlite.connect(db_path) as db:
        for table in TARGET_TABLES:
            report = await _backfill_table(db, table, user_id, dry_run=dry_run)
            reports.append(report)
            logger.info(
                "table=%s added_column=%s rows_updated=%d indexed=%s",
                report.table,
                report.added_column,
                report.rows_updated,
                report.indexed,
            )
        if not dry_run:
            await db.commit()

    return reports


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 27 Part 2 — backfill user_id on legacy SQLite tables.",
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_SUPERUSER_EMAIL,
        help=f"Superuser email to look up in app.users (default: {DEFAULT_SUPERUSER_EMAIL}).",
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"Path to the legacy SQLite database (default: {DB_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    try:
        reports = asyncio.run(
            run(email=args.email, db_path=args.db_path, dry_run=args.dry_run)
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    print("\n=== Phase 27 Part 2 backfill summary ===")
    print(f"db: {args.db_path}")
    print(f"dry-run: {args.dry_run}")
    for report in reports:
        print(
            f"  {report.table:<16} added_column={report.added_column!s:<5} "
            f"rows_updated={report.rows_updated:<6} indexed={report.indexed}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
