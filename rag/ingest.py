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

load_dotenv()

console = Console()

VAULT_PATH = Path(os.environ["VAULT_PATH"])
QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
VECTOR_SIZE = 384  # bge-small-en-v1.5 output dimension

SKIP_FOLDERS = {"_publish", ".obsidian", ".git", "rag", "node_modules"}
STATE_FILE = Path(__file__).parent / ".ingest_state.json"

CHUNK_SIZE = 400
CHUNK_OVERLAP = 50


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


def chunks_from_file(file_path: Path) -> list[dict]:
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
            uid = hashlib.sha256(f"{rel_path}::{heading}::{i}".encode()).hexdigest()[:16]
            result.append({
                "id": uid,
                "text": chunk_text,
                "metadata": {
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
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


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


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Main ───────────────────────────────────────────────────────────────────────

def collect_files(changed_only: bool, single_file: str | None) -> list[Path]:
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


def run(changed_only: bool = False, single_file: str | None = None) -> None:
    console.rule("[bold blue]NEXUS Ingestion Pipeline[/bold blue]")
    t0 = time.time()

    client = get_client()
    ensure_collection(client)

    files = collect_files(changed_only, single_file)
    if not files:
        console.print("[yellow]No files to index.[/yellow]")
        return

    console.print(f"[cyan]Indexing {len(files)} file(s)…[/cyan]")
    console.print(f"[dim]Loading embedding model {EMBED_MODEL}…[/dim]")
    embedder = TextEmbedding(model_name=EMBED_MODEL)

    state = load_state()
    total_chunks = 0
    BATCH_SIZE = 32

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
            chunks = chunks_from_file(file_path)

            if chunks:
                batch.extend(chunks)
                total_chunks += len(chunks)

                if len(batch) >= BATCH_SIZE:
                    upsert_batch(client, embedder, batch)
                    batch = []

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index NEXUS vault into Qdrant")
    parser.add_argument("--changed", action="store_true", help="Only index files changed since last run")
    parser.add_argument("--file", type=str, default=None, help="Index a single file (relative to vault root)")
    args = parser.parse_args()

    run(changed_only=args.changed, single_file=args.file)
