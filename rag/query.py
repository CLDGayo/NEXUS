"""
NEXUS RAG — Query Engine

Embeds a user question, retrieves relevant vault chunks from Qdrant,
builds a context-aware prompt, and streams the answer from Groq.
"""

import os
from dataclasses import dataclass
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
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

TOP_K = 6
SCORE_THRESHOLD = 0.35

# Module-level embedder — loaded once, reused across requests
_embedder: TextEmbedding | None = None


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


SYSTEM_PROMPT = """You are NEXUS, Clarence Lloyd Gayo's personal AI assistant with deep knowledge of his second brain vault.

You answer questions using ONLY the vault notes provided as context. Your goal:
- Give precise, useful answers grounded in the actual notes
- Cite sources using the format [Note: filename] after each claim
- If the context doesn't contain the answer, say so honestly — don't hallucinate
- Surface connections between ideas when relevant
- Match the user's tone: direct and conversational

You are Clarence's thinking partner, not a generic chatbot."""


@dataclass
class Source:
    file: str
    heading: str
    score: float
    text: str


@dataclass
class QueryResult:
    sources: list[Source]
    context: str


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

    sources: list[Source] = []
    context_parts: list[str] = []

    for hit in response.points:
        payload = hit.payload or {}
        sources.append(Source(
            file=payload.get("file", "unknown"),
            heading=payload.get("heading", ""),
            score=hit.score,
            text=payload.get("text", ""),
        ))
        context_parts.append(f"[Note: {payload.get('file', 'unknown')}]\n{payload.get('text', '')}")

    return QueryResult(
        sources=sources,
        context="\n\n---\n\n".join(context_parts),
    )


def build_messages(question: str, context: str, history: list[dict]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-6:])
    messages.append({
        "role": "user",
        "content": f"Vault context:\n\n{context}\n\n---\n\nQuestion: {question}",
    })
    return messages


async def stream_answer(
    question: str,
    history: list[dict] | None = None,
    top_k: int = TOP_K,
) -> AsyncIterator[tuple[str, list[Source]]]:
    """Yields (token, sources) — sources only non-empty on first yield."""
    result = await retrieve(question, top_k=top_k)
    messages = build_messages(question, result.context, history or [])

    groq = AsyncGroq(api_key=GROQ_API_KEY)
    stream = await groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        stream=True,
        temperature=0.3,
        max_tokens=1024,
    )

    first = True
    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            if first:
                yield token, result.sources
                first = False
            else:
                yield token, []
