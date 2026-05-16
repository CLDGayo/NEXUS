"""
NEXUS RAG — Query Engine

Embeds a user question, retrieves relevant vault chunks from Qdrant,
deduplicates them by source file, builds a numbered context-aware prompt,
streams the answer from Groq, and produces follow-up suggestions.
"""

from __future__ import annotations

import json
import os
import os.path
import re
from dataclasses import dataclass, field
from typing import AsyncIterator

from dotenv import load_dotenv
from fastembed import TextEmbedding
from groq import AsyncGroq
from qdrant_client import AsyncQdrantClient

load_dotenv()

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
COLLECTION = os.environ.get("QDRANT_COLLECTION", "nexus-vault")
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
FOLLOWUP_MODEL = os.environ.get("FOLLOWUP_MODEL", "llama-3.1-8b-instant")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

TOP_K = 6
SCORE_THRESHOLD = 0.35

_embedder: TextEmbedding | None = None


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


SYSTEM_PROMPT = """You are NEXUS, Clarence Lloyd Gayo's personal AI assistant grounded in his second-brain vault.

Answer using ONLY the numbered sources provided as context.

CITATION RULES — STRICT:
- Cite with bracketed numbers only: [1], [2], [3]. Multiple sources: [1][2].
- The numbers map to the "Source [N]:" entries in the context — never invent numbers.
- NEVER write file paths, file names, .md extensions, folder names, or "[Note: ...]". Numbers only.
- If the context cannot answer the question, say so plainly. Do not fabricate.

Tone: direct, conversational, and useful. You are Clarence's thinking partner."""


FOLLOWUP_PROMPT = """Based on the user's question and the answer that was just given, generate exactly 3 short, highly relevant follow-up questions the user might ask next.

Rules:
- Each question must be under 80 characters.
- Questions should explore deeper, related, or adjacent angles — not restate the original.
- Respond ONLY with a JSON array of 3 strings. No prose, no markdown.

Example output: ["What about X?", "How does Y compare?", "When should I use Z?"]"""


@dataclass
class Source:
    file: str
    heading: str
    score: float
    text: str


@dataclass
class Chunk:
    heading: str
    score: float
    text: str


@dataclass
class DocumentSource:
    index: int
    file: str
    display: str
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class QueryResult:
    sources: list[DocumentSource]
    context: str


def display_name(file: str) -> str:
    """'00 - Inbox/Clyde - New Enhanced CV.md' -> 'Clyde - New Enhanced CV'."""
    return os.path.splitext(os.path.basename(file))[0]


def dedupe_sources(raw: list[Source]) -> list[DocumentSource]:
    """Group chunks by file, preserve first-seen order, assign 1-based index."""
    by_file: dict[str, list[Chunk]] = {}
    order: list[str] = []
    for s in raw:
        if s.file not in by_file:
            by_file[s.file] = []
            order.append(s.file)
        by_file[s.file].append(Chunk(heading=s.heading, score=s.score, text=s.text))
    return [
        DocumentSource(
            index=i + 1,
            file=f,
            display=display_name(f),
            chunks=sorted(by_file[f], key=lambda c: -c.score),
        )
        for i, f in enumerate(order)
    ]


def format_context(sources: list[DocumentSource]) -> str:
    """Strict numbered-source format the LLM is instructed to cite."""
    parts: list[str] = []
    for ds in sources:
        merged = "\n\n".join(c.text for c in ds.chunks if c.text)
        parts.append(f"Source [{ds.index}]: {ds.display}\nContent: {merged}")
    return "\n\n---\n\n".join(parts)


async def retrieve(question: str, top_k: int = TOP_K) -> QueryResult:
    embedder = get_embedder()
    query_vector = list(embedder.embed([question]))[0].tolist()

    client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    response = await client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=top_k,
        score_threshold=SCORE_THRESHOLD,
        with_payload=True,
    )
    await client.close()

    raw: list[Source] = []
    for hit in response.points:
        payload = hit.payload or {}
        raw.append(Source(
            file=payload.get("file", "unknown"),
            heading=payload.get("heading", ""),
            score=hit.score,
            text=payload.get("text", ""),
        ))

    deduped = dedupe_sources(raw)
    return QueryResult(sources=deduped, context=format_context(deduped))


def build_messages(
    question: str,
    context: str,
    history: list[dict],
    system_prompt: str | None = None,
) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT}
    ]
    messages.extend(history[-6:])
    messages.append({
        "role": "user",
        "content": f"Vault context:\n\n{context}\n\n---\n\nQuestion: {question}",
    })
    return messages


def _source_to_dict(ds: DocumentSource) -> dict:
    return {
        "index": ds.index,
        "file": ds.file,
        "display": ds.display,
        "chunks": [
            {"heading": c.heading, "score": round(c.score, 3), "text": c.text}
            for c in ds.chunks
        ],
    }


def _parse_followups(raw: str) -> list[str]:
    """Tolerant parse: prefer JSON array, fall back to line splitting."""
    cleaned = raw.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()][:3]
    except (json.JSONDecodeError, ValueError):
        pass

    lines = [re.sub(r"^[\s\-\*\d\.\)]+", "", line).strip(' "\'')
             for line in cleaned.splitlines()]
    return [line for line in lines if line][:3]


async def generate_followups(
    question: str, answer: str, model: str | None = None
) -> list[str]:
    """Quick secondary call to suggest 3 follow-up questions. Never raises."""
    if not answer.strip():
        return []
    try:
        groq = AsyncGroq(api_key=GROQ_API_KEY)
        resp = await groq.chat.completions.create(
            model=model or FOLLOWUP_MODEL,
            messages=[
                {"role": "system", "content": FOLLOWUP_PROMPT},
                {"role": "user", "content": f"Question:\n{question}\n\nAnswer:\n{answer}"},
            ],
            temperature=0.5,
            max_tokens=200,
        )
        content = resp.choices[0].message.content or ""
        return _parse_followups(content)
    except Exception:
        return []


async def stream_answer(
    question: str,
    history: list[dict] | None = None,
    top_k: int = TOP_K,
    groq_model: str | None = None,
    followup_model: str | None = None,
    system_prompt: str | None = None,
) -> AsyncIterator[dict]:
    """Yields tagged events: status / sources / token / followups.

    Event shapes:
      {"type": "status", "stage": "searching"|"retrieved"|"generating", "count"?: int}
      {"type": "sources", "items": list[dict]}     # DocumentSource serialized
      {"type": "token",   "content": str}
      {"type": "followups","items": list[str]}
    """
    yield {"type": "status", "stage": "searching"}
    result = await retrieve(question, top_k=top_k)
    yield {"type": "status", "stage": "retrieved", "count": len(result.sources)}
    yield {"type": "sources", "items": [_source_to_dict(s) for s in result.sources]}
    yield {"type": "status", "stage": "generating"}

    messages = build_messages(
        question, result.context, history or [], system_prompt=system_prompt
    )
    groq = AsyncGroq(api_key=GROQ_API_KEY)
    stream = await groq.chat.completions.create(
        model=groq_model or GROQ_MODEL,
        messages=messages,
        stream=True,
        temperature=0.3,
        max_tokens=1024,
    )

    full_answer = ""
    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            full_answer += token
            yield {"type": "token", "content": token}

    followups = await generate_followups(question, full_answer, model=followup_model)
    if followups:
        yield {"type": "followups", "items": followups}
