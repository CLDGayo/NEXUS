"""
NEXUS RAG — Chainlit Chat App

Web-based chat interface for querying your Obsidian vault.
Run with: chainlit run chat.py --port 8501
"""

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import chainlit as cl
from dotenv import load_dotenv
from fastembed import TextEmbedding
from pypdf import PdfReader

from ingest import chunks_from_file, ensure_collection, get_client, upsert_batch
from query import Source, stream_answer

load_dotenv()

VAULT_PATH = Path(os.environ["VAULT_PATH"])
INBOX = VAULT_PATH / "00 - Inbox"

# Shared embedder — loaded once per process
_embedder: TextEmbedding | None = None


def get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
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


def save_to_inbox(title: str, content: str, source_filename: str) -> Path:
    """Write extracted content as a markdown note into 00 - Inbox."""
    INBOX.mkdir(exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    note_name = f"{date} {title}.md"
    note_path = INBOX / note_name

    frontmatter = (
        f"---\n"
        f"title: {title}\n"
        f"source: {source_filename}\n"
        f"date: {date}\n"
        f"tags: [inbox, pdf-import]\n"
        f"---\n\n"
    )
    note_path.write_text(frontmatter + content, encoding="utf-8")
    return note_path


def index_note(note_path: Path) -> int:
    """Chunk, embed, and upsert a single note into Qdrant. Returns chunk count."""
    client = get_client()
    ensure_collection(client)
    chunks = chunks_from_file(note_path)
    if chunks:
        upsert_batch(client, get_embedder(), chunks)
    return len(chunks)


def format_sources(sources: list[Source]) -> str:
    if not sources:
        return ""
    lines = ["\n\n---\n**Sources used:**"]
    seen: set[str] = set()
    for s in sources:
        key = f"{s.file}#{s.heading}"
        if key in seen:
            continue
        seen.add(key)
        score_pct = int(s.score * 100)
        label = f"`{s.file}`"
        if s.heading and s.heading != "Introduction":
            label += f" → *{s.heading}*"
        lines.append(f"- {label} ({score_pct}% match)")
    return "\n".join(lines)


@cl.on_chat_start
async def on_start():
    cl.user_session.set("history", [])
    await cl.Message(
        content=(
            "## NEXUS — Your Second Brain\n\n"
            "Ask me anything from your vault. I'll find the relevant notes and answer.\n\n"
            "*Try: \"What projects am I working on?\" or attach a PDF to ingest it into your vault.*"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    # ── Handle PDF uploads ────────────────────────────────────────────────────
    pdf_elements = [el for el in (message.elements or []) if getattr(el, "mime", "") == "application/pdf"]

    if pdf_elements:
        for el in pdf_elements:
            status = cl.Message(content=f"Reading **{el.name}**…")
            await status.send()

            try:
                text = extract_pdf_text(el.path)
                if not text.strip():
                    await cl.Message(content=f"⚠️ Could not extract text from **{el.name}** — it may be a scanned image PDF.").send()
                    continue

                title = safe_stem(el.name)
                note_path = save_to_inbox(title, text, el.name)
                chunk_count = index_note(note_path)
                rel_path = str(note_path.relative_to(VAULT_PATH))

                await cl.Message(
                    content=(
                        f"**{el.name}** saved and indexed.\n\n"
                        f"- Note: `{rel_path}`\n"
                        f"- Chunks indexed: **{chunk_count}**\n"
                        f"- Available in this chat and all future sessions immediately."
                    )
                ).send()

            except Exception as e:
                await cl.Message(content=f"⚠️ Failed to process **{el.name}**: {e}").send()

        # If there's no question text alongside the upload, stop here
        if not message.content.strip():
            return

    # ── Handle text question ──────────────────────────────────────────────────
    question = message.content.strip()
    if not question:
        return

    history: list[dict] = cl.user_session.get("history", [])
    msg = cl.Message(content="")
    await msg.send()

    full_response = ""
    sources_appended = False
    all_sources: list[Source] = []

    try:
        async for token, sources in stream_answer(question, history=history):
            full_response += token
            await msg.stream_token(token)

            if sources and not sources_appended:
                all_sources = sources
                sources_appended = True

    except Exception as e:
        error_msg = str(e)
        if "GROQ_API_KEY" in error_msg or "authentication" in error_msg.lower():
            await msg.stream_token("\n\n⚠️ Groq API key missing — add it to `rag/.env`")
        elif "Connection" in error_msg or "refused" in error_msg:
            await msg.stream_token("\n\n⚠️ Cannot reach Qdrant. Open SSH tunnel: `ssh -L 6333:127.0.0.1:6333 root@72.62.196.231 -N -f`")
        else:
            await msg.stream_token(f"\n\n⚠️ Error: {error_msg}")

    if all_sources:
        source_text = format_sources(all_sources)
        await msg.stream_token(source_text)
        full_response += source_text

    await msg.update()

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": full_response.split("\n\n---\n**Sources")[0]})
    cl.user_session.set("history", history)
