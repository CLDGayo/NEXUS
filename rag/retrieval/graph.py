"""Graph retrieval arm — Phase 31 Postgres-backed.

Combines two cheap signals to surface notes that pure dense/sparse miss:

    1. **Entity resolution** — match terms in the user's query against the
       title + aliases of every Document the active tenant has indexed
       (BM25-lite over a tiny corpus, no Qdrant traffic). Top-N
       candidates become "seed" notes.

    2. **One-hop graph walk** — for each seed, fetch its outgoing and
       incoming wikilink neighbours from ``app.document_links``, scoped
       by the same tenant.

    3. **Best chunk per neighbour** — run a single dense-vector search
       against Qdrant filtered to the union of seed + neighbour file
       paths AND the tenant predicate. The reranker downstream gets
       chunks that are both graph-relevant and semantically close to
       the query.

Phase 31 — every read from the graph DB is filtered by ``tenant_id``.
The legacy ``rag/data/nexus_graph.db`` SQLite file is no longer
consulted; ``connect()`` now yields a SQLAlchemy session pointed at the
``app`` schema.
"""

from __future__ import annotations

import logging
import uuid

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from rag.config import settings
from rag.database.models import Tenant
from rag.ingest_v2.graph_db import connect, fetch_note_titles, neighbors_of
from rag.retrieval.dense import _encode_query, get_qdrant_client
from rag.retrieval.sparse import tokenize
from rag.retrieval.types import ScoredChunk

_log = logging.getLogger(__name__)


# Tuning constants. Kept here (not in settings) because they describe the
# retrieval algorithm rather than the deployment environment.
SEED_CANDIDATES: int = 3
MAX_NEIGHBOR_PATHS: int = 6


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------

def _score_candidate(
    query_tokens: set[str], title: str, aliases: tuple[str, ...]
) -> float:
    """Cheap token-overlap score. Higher when more query tokens hit the
    candidate's title or any of its aliases."""

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
    session, query: str, *, tenant_uuid: uuid.UUID, limit: int
) -> list[tuple[str, float]]:
    """Return up to ``limit`` ``(file, score)`` candidate seeds for the
    graph walk inside the active tenant."""

    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []

    notes = await fetch_note_titles(session, tenant_id=tenant_uuid)
    scored: list[tuple[str, float]] = []
    for file, title, aliases in notes:
        score = _score_candidate(query_tokens, title, aliases)
        if score > 0:
            scored.append((file, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Qdrant filtered search
# ---------------------------------------------------------------------------

def _compose_filter(paths: list[str], tenant_id: str) -> Filter:
    """Build a Qdrant ``Filter`` that requires tenant_id AND (if paths
    provided) at least one matching file path.

    ``tenant_id`` here is the slug stamped on Qdrant payloads (kept as
    str for backwards compat with the existing payload schema). The
    Postgres-side reads use the tenant UUID; the slug↔uuid translation
    happens in :func:`graph_search`.
    """

    must: list = [
        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
    ]
    if paths:
        must.append(
            Filter(
                should=[
                    FieldCondition(key="file", match=MatchValue(value=p))
                    for p in paths
                ]
            )
        )
    return Filter(must=must)


def _chunk_text_from_payload(payload: dict | None) -> str:
    if not payload:
        return ""
    for key in ("text", "content", "chunk_text", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def _fetch_chunks_by_files(
    query: str, paths: list[str], k: int, *, tenant_id: str
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
            query_filter=_compose_filter(paths, tenant_id),
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
    query: str,
    *,
    k: int = 20,
    tenant_id: str,
    tenant_uuid: uuid.UUID | None = None,
) -> list[ScoredChunk]:
    """Return up to ``k`` graph-expanded chunks for ``query`` owned by
    ``tenant_id`` (slug stamped on Qdrant payloads).

    Two tenant identifiers exist by design:
        * ``tenant_id`` — slug, used for Qdrant payload filter.
        * ``tenant_uuid`` — Postgres ``app.tenants.id``, used for the
          graph DB lookups. If not supplied, the function falls back to
          resolving the slug via the orchestrator (which carries both
          today). When neither path is wired, the graph arm degrades to
          an empty result rather than running an unscoped query.

    Empty list when:
        * the query has no usable tokens,
        * no titles in this tenant match any query token,
        * the graph DB lookup fails (defensive — never raises so the
          orchestrator's other arms still produce a fused result).
    """

    if not query.strip():
        return []

    try:
        async with connect() as session:
            resolved_uuid = tenant_uuid
            if resolved_uuid is None:
                lookup = await session.execute(
                    select(Tenant.id).where(Tenant.slug == tenant_id)
                )
                resolved_uuid = lookup.scalar_one_or_none()
                if resolved_uuid is None:
                    _log.warning(
                        "graph arm: slug=%s does not resolve to a tenant "
                        "uuid; returning empty rather than running unscoped.",
                        tenant_id,
                    )
                    return []

            seeds = await _resolve_seeds(
                session,
                query,
                tenant_uuid=resolved_uuid,
                limit=SEED_CANDIDATES,
            )
            if not seeds:
                return []

            paths: dict[str, None] = {}
            for seed_path, _score in seeds:
                paths.setdefault(seed_path, None)
                neighbours = await neighbors_of(
                    session, seed_path, tenant_id=resolved_uuid
                )
                for neighbour in neighbours:
                    paths.setdefault(neighbour, None)
                    if len(paths) >= MAX_NEIGHBOR_PATHS:
                        break
                if len(paths) >= MAX_NEIGHBOR_PATHS:
                    break
    except Exception as exc:
        _log.warning("graph arm: DB read failed: %s", exc)
        return []

    paths_list = list(paths.keys())[:MAX_NEIGHBOR_PATHS]
    return await _fetch_chunks_by_files(
        query, paths_list, k=k, tenant_id=tenant_id
    )
