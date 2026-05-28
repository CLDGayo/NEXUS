"""CLI for the Phase 4 ingest pipeline.

Usage:
    python -m rag.ingest_v2 init-collection [--collection NAME]
    python -m rag.ingest_v2 ingest <path>   --tenant SLUG [--collection NAME] [--dry-run]
    python -m rag.ingest_v2 ingest --vault  --tenant SLUG [--vault-root DIR] [--ext .md,.pdf]
                                            [--collection NAME] [--dry-run]

Phase 31 — ``--tenant`` is required for ingest. Every Qdrant payload is
stamped with the slug; the matching ``app.tenants`` row is looked up so
the per-tenant ``app.documents`` + ``app.document_links`` writes carry
the correct UUID.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import select

from rag.config import settings
from rag.database.engine import dispose_engine, get_sessionmaker
from rag.database.models import Tenant
from rag.ingest_v2.pipeline import (
    ingest_paths,
    iter_vault,
)
from rag.ingest_v2.qdrant_writer import init_collection


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag.ingest_v2",
        description="Nexus v2 ingest pipeline (multimodal + semantic + late chunking)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser(
        "init-collection",
        help="Create the target Qdrant collection if it does not exist.",
    )
    init_p.add_argument("--collection", default=None)
    init_p.add_argument(
        "--recreate", action="store_true",
        help="DROP and recreate the collection. Destroys data.",
    )

    ingest_p = sub.add_parser("ingest", help="Run the ingest pipeline.")
    ingest_p.add_argument("path", type=Path, nargs="?", default=None)
    ingest_p.add_argument(
        "--vault", action="store_true",
        help="Ingest the entire vault rooted at --vault-root (or VAULT_PATH).",
    )
    ingest_p.add_argument(
        "--vault-root", type=Path, default=None,
        help="Vault root directory (defaults to VAULT_PATH env).",
    )
    ingest_p.add_argument(
        "--ext", default=".md,.pdf",
        help="Comma-separated list of extensions to include (default: .md,.pdf).",
    )
    ingest_p.add_argument("--collection", default=None)
    ingest_p.add_argument(
        "--tenant",
        required=True,
        help=(
            "Tenant slug to attribute these chunks + documents to. "
            "Must already exist in app.tenants."
        ),
    )
    ingest_p.add_argument(
        "--dry-run", action="store_true",
        help="Run parse + chunk + late chunk but skip Qdrant writes.",
    )
    ingest_p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable INFO-level logging on the rag.* loggers.",
    )

    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _resolve_tenant(slug: str):
    """Look up the Tenant row by slug. Aborts the CLI if missing."""

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(Tenant).where(Tenant.slug == slug)
            )
        ).scalar_one_or_none()
    if row is None:
        raise SystemExit(
            f"ERROR: tenant slug {slug!r} not found in app.tenants. "
            "Provision it via POST /api/tenants first."
        )
    return row


async def _cmd_init_collection(args: argparse.Namespace) -> int:
    name = await init_collection(
        collection=args.collection, recreate=args.recreate
    )
    print(f"collection ready: {name}")
    return 0


async def _cmd_ingest(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose)

    tenant = await _resolve_tenant(args.tenant)

    if args.vault:
        vault_root = args.vault_root or Path(settings.vault_path)
        if not vault_root.is_dir():
            print(f"ERROR: vault root not found: {vault_root}", file=sys.stderr)
            return 2
        exts = [e.strip() for e in args.ext.split(",") if e.strip()]
        paths = iter_vault(vault_root, extensions=exts)
    elif args.path:
        if args.path.is_dir():
            paths = [p for p in args.path.rglob("*") if p.is_file()]
        else:
            paths = [args.path]
        vault_root = None
    else:
        print(
            "ERROR: pass a positional <path> or --vault (with optional "
            "--vault-root).",
            file=sys.stderr,
        )
        return 2

    if not paths:
        print("no files matched; nothing to ingest")
        return 0

    print(
        f"ingesting {len(paths)} file(s) for tenant {tenant.slug} → "
        f"{args.collection or settings.ingest_qdrant_collection}"
    )
    if args.dry_run:
        print("(dry-run: no Qdrant writes)")

    results = await ingest_paths(
        paths,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        vault_root=vault_root,
        collection=args.collection,
        dry_run=args.dry_run,
    )

    succeeded = sum(1 for r in results if r.succeeded)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if r.error)
    total_chunks = sum(r.chunks_upserted for r in results)

    for r in results:
        if r.error:
            print(f"  ERROR  {r.source}: {r.error}")
        elif r.skipped:
            print(f"  skip   {r.source}: {r.skip_reason}")
        else:
            mark = "ok" if r.chunks_upserted else "dry"
            print(
                f"  {mark:6s} {r.source}: "
                f"emitted={r.chunks_emitted} upserted={r.chunks_upserted}"
            )

    print(
        f"summary: {succeeded} ok / {skipped} skipped / {failed} failed / "
        f"{total_chunks} chunks upserted"
    )
    return 0 if failed == 0 else 1


async def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "init-collection":
            return await _cmd_init_collection(args)
        if args.cmd == "ingest":
            return await _cmd_ingest(args)
        parser.print_help(sys.stderr)
        return 2
    finally:
        await dispose_engine()


def run() -> None:
    """Entrypoint used by ``python -m rag.ingest_v2``."""

    # Avoid surprising users when CWD is the project root.
    sys.path.insert(0, os.getcwd())
    code = asyncio.run(main())
    sys.exit(code)
