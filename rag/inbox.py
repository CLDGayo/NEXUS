"""Framework-agnostic helpers for writing files into 00 - Inbox/ and indexing them.

Both the FastAPI upload router and the legacy Chainlit chat path import from here.
Keep this module free of FastAPI and Chainlit imports so it stays reusable.
"""

import hashlib
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import frontmatter
from fastembed import TextEmbedding
from pypdf import PdfReader
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

from ingest import COLLECTION, chunks_from_file, ensure_collection, get_client, upsert_batch

log = logging.getLogger(__name__)

VAULT_PATH = Path(os.environ["VAULT_PATH"])
INBOX = VAULT_PATH / "00 - Inbox"

# Persistent cache dir — defaults to ~/.cache/fastembed-nexus to survive macOS's
# periodic cleanup of /var/folders/.../T/ (which is fastembed's default location).
FASTEMBED_CACHE_DIR = Path(
    os.environ.get("FASTEMBED_CACHE_DIR", str(Path.home() / ".cache" / "fastembed-nexus"))
)

_embedder: TextEmbedding | None = None


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        FASTEMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _embedder = TextEmbedding(
            model_name=os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            cache_dir=str(FASTEMBED_CACHE_DIR),
        )
    return _embedder


def safe_stem(name: str) -> str:
    """Normalise a filename into a safe vault note name."""
    stem = Path(name).stem
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^\w\s-]", "", stem).strip()
    return re.sub(r"[\s_]+", " ", stem)


def extract_pdf_text(path: str) -> str:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())


def compute_content_hash(data: bytes | str) -> str:
    """SHA-256 hex digest. Pass bytes for binary inputs (PDFs), str for text."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def delete_vectors_for_file(rel_path: str) -> None:
    """Delete all chunks whose payload.file matches rel_path. Best-effort — never raises."""
    try:
        client = get_client()
        client.delete(
            collection_name=COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="file", match=MatchValue(value=rel_path))]
                )
            ),
            wait=True,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort GC
        log.warning("Vector GC failed for %s: %s", rel_path, exc)


def unique_inbox_path(target: Path) -> Path:
    """Return a path that does not yet exist, suffixing with ' (2)', ' (3)', ... if needed."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 2
    while True:
        candidate = target.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def write_note_at(
    target: Path,
    *,
    title: str,
    content: str,
    source_filename: str,
    tags: list[str],
    content_hash: str,
    extra_meta: dict | None = None,
    preserve_existing_yaml: bool = False,
) -> Path:
    """Write a note at an exact path, injecting frontmatter (incl. content_hash).

    If preserve_existing_yaml is True and ``content`` already starts with a YAML
    frontmatter block, the user's keys are preserved; ``content_hash`` and
    ``date_ingested`` are always set/overwritten, and title/source/date/tags
    are filled in only when missing.
    """
    INBOX.mkdir(exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")

    if preserve_existing_yaml and content.startswith("---\n") and "\n---\n" in content[4:]:
        post = frontmatter.loads(content)
    else:
        post = frontmatter.Post(content)

    post.metadata.setdefault("title", title)
    post.metadata.setdefault("source", source_filename)
    post.metadata.setdefault("date", date)
    post.metadata.setdefault("tags", list(tags))
    post["content_hash"] = content_hash
    post["date_ingested"] = date
    if extra_meta:
        post.metadata.update(extra_meta)

    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return target


def save_to_inbox(
    title: str,
    content: str,
    source_filename: str,
    *,
    tags: list[str] | None = None,
    content_hash: str | None = None,
) -> Path:
    """Write extracted content as a markdown note into 00 - Inbox/.

    Filename collisions are handled by ``unique_inbox_path``. If
    ``content_hash`` is omitted, it is computed from ``content``.
    """
    if tags is None:
        tags = ["inbox", "pdf-import"]
    if content_hash is None:
        content_hash = compute_content_hash(content)
    date = datetime.now().strftime("%Y-%m-%d")
    note_path = unique_inbox_path(INBOX / f"{date} {title}.md")
    return write_note_at(
        note_path,
        title=title,
        content=content,
        source_filename=source_filename,
        tags=tags,
        content_hash=content_hash,
    )


def index_note(note_path: Path) -> int:
    """Chunk, embed, and upsert a single note into Qdrant. Returns chunk count."""
    client = get_client()
    ensure_collection(client)
    chunks = chunks_from_file(note_path)
    if chunks:
        upsert_batch(client, get_embedder(), chunks)
    return len(chunks)
