"""
NEXUS RAG — Ingestion Pipeline

Scans the Obsidian vault, chunks markdown files, embeds with fastembed,
and upserts into Qdrant. Run this after adding or editing notes.

Usage:
    python ingest.py              # Full reindex
    python ingest.py --changed    # Only files modified since last run
    python ingest.py --file "06 - Concepts/My Note.md"  # Single file
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import frontmatter
from dotenv import load_dotenv
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from events import publish_sync
from ingest_v2.graph_db import connect as graph_connect
from ingest_v2.graph_db import resolve_link_targets
from ingest_v2.graph_index import index_file_links

load_dotenv()

console = Console()

VAULT_PATH = Path(os.environ["VAULT_PATH"])
QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
VECTOR_SIZE = 384  # bge-small-en-v1.5 output dimension

SKIP_FOLDERS = {"_publish", ".obsidian", ".git", "rag", "node_modules", "04 - Archive"}
STATE_FILE = Path(__file__).parent / ".ingest_state.json"

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50

# qdrant-client defaults to a 5s HTTP read timeout — too tight for upserts that
# travel over the public HTTPS endpoint. Raise it (env-overridable for ops).
QDRANT_TIMEOUT = int(os.environ.get("QDRANT_TIMEOUT", "60"))

# Phase 29 — default tenant the CLI ingests against when ``--tenant`` is
# absent. Must match ``DEFAULT_TENANT_SLUG`` in rag.database (SQLite) and
# the seed slug in the Alembic migration ``0002_phase29_multi_tenancy``.
DEFAULT_TENANT_SLUG = os.environ.get("DEFAULT_TENANT_SLUG", "hunter")


# ── Markdown chunker ──────────────────────────────────────────────────────────

def split_by_headers(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_heading = "Introduction"
    current_lines: list[str] = []

    for line in lines:
        match = re.match(r"^(#{1,4})\s+(.+)", line)
        if match:
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return [(h, t) for h, t in sections if t]


def naive_token_count(text: str) -> int:
    return len(text) // 4


def chunk_section(heading: str, text: str) -> list[str]:
    if naive_token_count(text) <= CHUNK_SIZE:
        return [f"## {heading}\n\n{text}"] if text else []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = naive_token_count(para)
        if current_tokens + para_tokens > CHUNK_SIZE and current_parts:
            chunks.append(f"## {heading}\n\n" + "\n\n".join(current_parts))
            overlap_parts: list[str] = []
            overlap_tokens = 0
            for part in reversed(current_parts):
                t = naive_token_count(part)
                if overlap_tokens + t <= CHUNK_OVERLAP:
                    overlap_parts.insert(0, part)
                    overlap_tokens += t
                else:
                    break
            current_parts = overlap_parts
            current_tokens = overlap_tokens

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append(f"## {heading}\n\n" + "\n\n".join(current_parts))

    return chunks


def extract_wikilinks(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]|#]+)(?:[|\#][^\]]*)?\]\]", text)


def chunks_from_file(
    file_path: Path,
    *,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
) -> list[dict]:
    try:
        post = frontmatter.load(str(file_path))
    except Exception:
        return []

    content: str = post.content.strip()
    if not content:
        return []

    meta = post.metadata
    rel_path = str(file_path.relative_to(VAULT_PATH))
    folder = rel_path.split("/")[0] if "/" in rel_path else "root"

    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, list):
        tags = [str(t) for t in raw_tags]
    elif isinstance(raw_tags, str):
        tags = [raw_tags]
    else:
        tags = []

    wikilinks = extract_wikilinks(content)
    mtime = int(file_path.stat().st_mtime)

    sections = split_by_headers(content) or [("Content", content)]

    result: list[dict] = []
    for heading, section_text in sections:
        for i, chunk_text in enumerate(chunk_section(heading, section_text)):
            # Phase 29 — make point ids tenant-unique so two tenants
            # ingesting the same relative path do not collide on the
            # int(hash) % 2**63 reduction (which would silently overwrite
            # one tenant's chunks with the other's).
            uid = hashlib.sha256(
                f"{tenant_slug}::{rel_path}::{heading}::{i}".encode()
            ).hexdigest()[:16]
            result.append({
                "id": uid,
                "text": chunk_text,
                "metadata": {
                    "tenant_id": tenant_slug,
                    "file": rel_path,
                    "folder": folder,
                    "title": meta.get("title", file_path.stem),
                    "heading": heading,
                    "tags": tags,
                    "wikilinks": wikilinks,
                    "mtime": mtime,
                    "chunk_index": i,
                    "text": chunk_text,
                },
            })

    return result


# ── Qdrant helpers ─────────────────────────────────────────────────────────────

def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=QDRANT_TIMEOUT)


def ensure_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        console.print(f"[green]Created collection:[/green] {COLLECTION}")
    else:
        console.print(f"[dim]Collection exists:[/dim] {COLLECTION}")

    # Idempotent payload indexes. `file` is required for fast filter-delete
    # by file path; `tenant_id` is required for strict tenancy filtering
    # on every retrieval call (Phase 29). Both wrapped in try/except — the
    # client raises on duplicate index creation.
    for field in ("file", "tenant_id"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema="keyword",
            )
        except Exception:  # noqa: BLE001 — already exists is the common case
            pass


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Main ───────────────────────────────────────────────────────────────────────

def collect_files(
    changed_only: bool, single_file: str | None
) -> list[Path]:
    if single_file:
        p = VAULT_PATH / single_file
        if not p.exists():
            console.print(f"[red]File not found:[/red] {p}")
            sys.exit(1)
        return [p]

    all_md = [
        f for f in VAULT_PATH.rglob("*.md")
        if not any(skip in f.parts for skip in SKIP_FOLDERS)
    ]

    if not changed_only:
        return all_md

    state = load_state()
    return [f for f in all_md if str(f) not in state or state[str(f)] != int(f.stat().st_mtime)]


def upsert_batch(client: QdrantClient, embedder: TextEmbedding, chunks: list[dict]) -> None:
    texts = [c["text"] for c in chunks]
    vectors = list(embedder.embed(texts))

    points = [
        PointStruct(
            id=int(c["id"], 16) % (2**63),
            vector=vec.tolist(),
            payload=c["metadata"],
        )
        for c, vec in zip(chunks, vectors)
    ]
    client.upsert(collection_name=COLLECTION, points=points, wait=True)


# ── Graph indexing (Phase 23 — Architect option 4.A) ──────────────────────────
#
# Production ingest stays on v1, but each processed file also gets its
# outbound wikilinks recorded into the v2 ``vault_notes`` + ``vault_links``
# SQLite graph so ``rag.orchestrator.nodes.retrieve_graph_node`` has data
# to expand over. ``wikilinks_in`` is computed on-the-fly at retrieval
# time via ``graph_db.neighbors_of`` (forward + reverse) — no Qdrant
# payload migration. Paths are stored as relative strings so they match
# the Qdrant ``file`` payload key used by ``retrieve_graph_node``'s
# filtered chunk fetch.

async def _index_graph_for_files(
    file_paths: list[Path], *, tenant_slug: str
) -> tuple[int, int]:
    """Upsert one ``app.documents`` row + outbound ``app.document_links``
    per file (scoped to the active tenant), then resolve every
    ``dst_target`` against known titles/aliases inside that tenant.

    Phase 31 — replaces the legacy ``vault_notes`` / ``vault_links``
    SQLite writes. The tenant uuid is resolved via ``app.tenants`` once
    per run; missing tenants abort the graph step (but Qdrant writes
    already completed).

    Returns ``(documents_indexed, edges_resolved)``. Files that fail to
    parse are skipped — they were also absent from Qdrant for the same
    reason, so the graph and the vector store stay consistent.
    """

    if not file_paths:
        return 0, 0

    from sqlalchemy import select
    from rag.database.models import Tenant

    indexed = 0
    async with graph_connect() as session:
        tenant_row = (
            await session.execute(
                select(Tenant).where(Tenant.slug == tenant_slug)
            )
        ).scalar_one_or_none()
        if tenant_row is None:
            raise RuntimeError(
                f"phase31: tenant slug {tenant_slug!r} not found in "
                "app.tenants; graph indexing aborted."
            )
        tenant_id = tenant_row.id
        for fp in file_paths:
            try:
                post = frontmatter.load(str(fp))
            except Exception:  # noqa: BLE001
                continue
            body = post.content
            fm = dict(post.metadata)
            rel = Path(str(fp.relative_to(VAULT_PATH)))
            await index_file_links(
                session,
                tenant_id=tenant_id,
                path=rel,
                body=body,
                frontmatter=fm,
                vault_root=Path(VAULT_PATH),
            )
            indexed += 1
        resolved = await resolve_link_targets(session, tenant_id=tenant_id)
    return indexed, resolved


def run(
    changed_only: bool = False,
    single_file: str | None = None,
    *,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
) -> None:
    console.rule(
        f"[bold blue]NEXUS Ingestion Pipeline[/bold blue] "
        f"[dim](tenant={tenant_slug})[/dim]"
    )
    t0 = time.time()

    client = get_client()
    ensure_collection(client)

    files = collect_files(changed_only, single_file)
    if not files:
        console.print("[yellow]No files to index.[/yellow]")
        return

    console.print(f"[cyan]Indexing {len(files)} file(s)…[/cyan]")
    console.print(f"[dim]Loading embedding model {EMBED_MODEL}…[/dim]")
    from inbox import FASTEMBED_CACHE_DIR
    FASTEMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    embedder = TextEmbedding(model_name=EMBED_MODEL, cache_dir=str(FASTEMBED_CACHE_DIR))

    state = load_state()
    total_chunks = 0
    BATCH_SIZE = 32

    # Phase 23 — collect every successfully-chunked file so we can update
    # the wikilink graph DB in a single async pass after the Qdrant work
    # finishes. A graph failure must not block Qdrant writes, so the
    # asyncio.run() call below is wrapped in its own try/except.
    graph_inputs: list[Path] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing", total=len(files))
        batch: list[dict] = []

        for file_path in files:
            progress.update(task, description=f"[dim]{file_path.name}[/dim]")
            file_t0 = time.time()
            try:
                chunks = chunks_from_file(file_path, tenant_slug=tenant_slug)
            except Exception as exc:  # noqa: BLE001
                publish_sync(
                    "ingest.failed",
                    {"file": str(file_path), "error": str(exc)},
                )
                state[str(file_path)] = int(file_path.stat().st_mtime)
                progress.advance(task)
                continue

            if chunks:
                batch.extend(chunks)
                total_chunks += len(chunks)
                graph_inputs.append(file_path)

                if len(batch) >= BATCH_SIZE:
                    upsert_batch(client, embedder, batch)
                    batch = []

            publish_sync(
                "ingest.complete",
                {
                    "file": str(file_path.relative_to(VAULT_PATH)),
                    "chunks": len(chunks),
                    "status": "indexed" if chunks else "empty",
                    "duration_ms": int((time.time() - file_t0) * 1000),
                },
            )

            state[str(file_path)] = int(file_path.stat().st_mtime)
            progress.advance(task)

        if batch:
            upsert_batch(client, embedder, batch)

    save_state(state)

    elapsed = time.time() - t0
    console.print(
        f"\n[green]Done.[/green] Indexed [bold]{total_chunks}[/bold] chunks "
        f"from [bold]{len(files)}[/bold] files in {elapsed:.1f}s"
    )
    console.print(
        f"Collection [bold]{COLLECTION}[/bold] → "
        f"{client.count(COLLECTION).count} total points"
    )

    # Phase 23 — populate the wikilink graph DB so the graph arm of the
    # orchestrator's retrieval pipeline has neighbors to expand to. Best
    # effort: the chat path degrades gracefully when graph_hits is empty.
    try:
        notes, edges = asyncio.run(
            _index_graph_for_files(graph_inputs, tenant_slug=tenant_slug)
        )
        console.print(
            f"[green]Graph indexed:[/green] {notes} notes, "
            f"{edges} resolved edges"
        )
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[yellow]Graph indexing failed (Qdrant unaffected): {exc}[/yellow]"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index NEXUS vault into Qdrant")
    parser.add_argument("--changed", action="store_true", help="Only index files changed since last run")
    parser.add_argument("--file", type=str, default=None, help="Index a single file (relative to vault root)")
    parser.add_argument(
        "--tenant",
        type=str,
        default=DEFAULT_TENANT_SLUG,
        help="Tenant slug stamped on every chunk payload (default: %(default)s)",
    )
    args = parser.parse_args()

    run(
        changed_only=args.changed,
        single_file=args.file,
        tenant_slug=args.tenant,
    )
