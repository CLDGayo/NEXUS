"""Graph retrieval arm.

Combines two cheap signals to surface notes that pure dense/sparse miss:

    1. **Entity resolution** — match terms in the user's query against the
       title + aliases of every indexed note (BM25 over a tiny corpus, no
       Qdrant traffic). Top-N candidates become "seed" notes.

    2. **One-hop graph walk** — for each seed, fetch its outgoing and
       incoming wikilink neighbors from ``vault_links``.

    3. **Best chunk per neighbor** — run a single dense-vector search
       against Qdrant filtered to the union of seed + neighbor file
       paths. The reranker downstream gets chunks that are both
       graph-relevant and semantically close to the query.

The output shape matches the dense/sparse arms so the orchestrator's
fuse node treats it as a third ranking list.
"""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

from rag.config import settings
from rag.ingest_v2.graph_db import connect, fetch_note_titles, neighbors_of
from rag.retrieval.dense import _encode_query, get_qdrant_client
from rag.retrieval.sparse import tokenize
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)


# Tuning constants. Kept here (not in settings) because they describe the
# retrieval algorithm rather than the deployment environment. Promote to
# settings if production wants to A/B them.
SEED_CANDIDATES: int = 3
MAX_NEIGHBOR_PATHS: int = 6


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------

def _score_candidate(
    query_tokens: set[str], title: str, aliases: tuple[str, ...]
) -> float:
    """Cheap token-overlap score. Higher when more query tokens hit the
    candidate's title or any of its aliases.

    Pure BM25 here would mean fitting an index per query — overkill for
    what is at most a few thousand titles. A length-normalized Jaccard
    over tokenized title+aliases is more than enough to surface obvious
    entity matches.
    """

    candidate_tokens: set[str] = set()
    for source in (title, *aliases):
        for tok in tokenize(source):
            candidate_tokens.add(tok)
    if not candidate_tokens or not query_tokens:
        return 0.0
    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0
    return len(overlap) / (len(query_tokens) + len(candidate_tokens) - len(overlap))


async def _resolve_seeds(
    conn: aiosqlite.Connection, query: str, *, limit: int
) -> list[tuple[str, float]]:
    """Return up to ``limit`` ``(path, score)`` candidate seeds for the
    graph walk. Empty list when no titles match any query token."""

    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []

    notes = await fetch_note_titles(conn)
    scored: list[tuple[str, float]] = []
    for path, title, aliases in notes:
        score = _score_candidate(query_tokens, title, aliases)
        if score > 0:
            scored.append((path, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Qdrant filtered search
# ---------------------------------------------------------------------------

def _file_filter(paths: list[str]) -> dict[str, Any]:
    """Build a Qdrant ``Filter`` payload that ORs across ``file`` values."""

    return {
        "should": [
            {"key": "file", "match": {"value": path}} for path in paths
        ]
    }


def _chunk_text_from_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in ("text", "content", "chunk_text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def _fetch_chunks_by_files(
    query: str, paths: list[str], k: int
) -> list[ScoredChunk]:
    if not paths:
        return []

    client = get_qdrant_client()
    try:
        vector = _encode_query(query)
    except Exception as exc:  # pragma: no cover - embed cold-start failure
        _log.error("graph arm: query embed failed: %s", exc)
        return []

    try:
        response = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=k,
            with_payload=True,
            query_filter=_file_filter(paths),
        )
    except Exception as exc:
        _log.warning("graph arm: dense filtered search failed: %s", exc)
        return []

    out: list[ScoredChunk] = []
    for point in response.points:
        payload = dict(point.payload or {})
        out.append(
            ScoredChunk(
                id=str(point.id),
                text=_chunk_text_from_payload(payload),
                score=float(point.score),
                metadata=payload,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def graph_search(
    query: str, *, k: int = 20
) -> list[ScoredChunk]:
    """Return up to ``k`` graph-expanded chunks for ``query``.

    Empty list when:
        * the query has no usable tokens,
        * no titles match any query token,
        * the graph DB is missing/empty,
        * the Qdrant filtered call fails (defensive: never raises so the
          orchestrator's other arms still produce a fused result).
    """

    if not query.strip():
        return []

    try:
        async with connect() as conn:
            seeds = await _resolve_seeds(conn, query, limit=SEED_CANDIDATES)
            if not seeds:
                return []

            paths: dict[str, None] = {}
            for seed_path, _ in seeds:
                paths.setdefault(seed_path, None)
                neighbors = await neighbors_of(conn, seed_path)
                for neighbor in neighbors:
                    paths.setdefault(neighbor, None)
                    if len(paths) >= MAX_NEIGHBOR_PATHS:
                        break
                if len(paths) >= MAX_NEIGHBOR_PATHS:
                    break
    except Exception as exc:
        _log.warning("graph arm: DB read failed: %s", exc)
        return []

    paths_list = list(paths.keys())[:MAX_NEIGHBOR_PATHS]
    return await _fetch_chunks_by_files(query, paths_list, k=k)
