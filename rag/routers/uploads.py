"""Direct file upload — content-hash dedup, vector GC, save to Inbox, index.

The endpoint stays single-file; the SPA loops over a staged batch to drive a
per-file progress UI. See plan: content-hash dedup, vector GC, batch uploads.
"""

import logging
from pathlib import Path

import frontmatter
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from inbox import (
    INBOX,
    VAULT_PATH,
    compute_content_hash,
    delete_vectors_for_file,
    index_note,
    safe_stem,
    write_note_at,
)
from rag.vision_pdf import caption_pdf_for_upload
from routers.deps import require_auth

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"], dependencies=[Depends(require_auth)])

ALLOWED_EXTS = {".md", ".txt", ".pdf"}
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
UPLOAD_TAGS = ["inbox", "upload"]


async def _extract_text(ext: str, data: bytes) -> str:
    """Decode/extract text per file type.

    For PDFs, embedded images are extracted and captioned via the vision LLM
    (Phase 16); captions are interleaved into the per-page text so they flow
    through the same chunker + embedder as native PDF text. If pypdf yields
    no text but vision produces ≥1 caption, the document is still accepted
    (scanned-PDF / image-only path).

    Raises HTTPException on empty/unscannable.
    """
    if ext == ".md":
        return data.decode("utf-8", errors="replace")
    if ext == ".txt":
        text = data.decode("utf-8", errors="replace")
        if not text.strip():
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return text
    # .pdf — text via pypdf + vision captions via fitz/llama-4-scout
    body, caption_count = await caption_pdf_for_upload(data)
    if not body.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "PDF could not be parsed: pypdf returned no text and vision "
                "captioning produced no descriptions. Try OCR or a re-export."
            ),
        )
    if caption_count > 0:
        log.info("pdf.vision_captions: %d caption(s) injected", caption_count)
    return body


@router.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    name = Path(file.filename).name  # strip any directory components
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext!r}. Allowed: .md, .txt, .pdf",
        )

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    text = await _extract_text(ext, data)
    # PDFs: hash raw bytes (avoids pypdf extraction non-determinism).
    # .md/.txt: hash decoded UTF-8 text.
    content_hash = compute_content_hash(data if ext == ".pdf" else text)

    title = safe_stem(name)
    target = INBOX / f"{title}.md"
    rel_path = str(target.relative_to(VAULT_PATH))

    if target.exists():
        existing_hash = frontmatter.load(str(target)).metadata.get("content_hash")
        if existing_hash == content_hash:
            return {
                "success": True,
                "filename": name,
                "note_path": rel_path,
                "status": "skipped",
                "chunks_indexed": 0,
                "message": f"File '{name}' is identical to existing document. Skipped.",
            }
        delete_vectors_for_file(rel_path)
        status = "updated"
    else:
        status = "created"

    write_note_at(
        target,
        title=title,
        content=text,
        source_filename=name,
        tags=UPLOAD_TAGS,
        content_hash=content_hash,
        preserve_existing_yaml=(ext == ".md"),
    )

    try:
        chunk_count = index_note(target)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Saved to Inbox but indexing failed: {exc}. "
                "Re-run `python ingest.py --changed` to retry."
            ),
        ) from exc

    return {
        "success": True,
        "filename": name,
        "note_path": rel_path,
        "status": status,
        "chunks_indexed": chunk_count,
    }
