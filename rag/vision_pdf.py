"""PDF image extraction + vision captioning (Phase 16).

PyMuPDF (``fitz``) pulls embedded images from each PDF page; each surviving
blob is base64-encoded and sent to the existing LiteLLM-proxied vision model
(``settings.vision_model``, default ``groq-llama-4-scout``) via the shared
``chat_complete`` client. Captions are interleaved into the per-page text so
they flow through the same chunker + embedder as native PDF text.

Public surface:

* :func:`extract_pdf_captions` — raw extraction; returns per-page caption
  lists. Used by both upload and v2 ingest paths.
* :func:`caption_pdf_for_upload` — convenience wrapper that interleaves
  caption lines into pypdf-extracted per-page text and returns the merged
  body string ready for ``write_note_at``.
* :func:`format_caption_appendix` — render captions as a Markdown block for
  the v2 Docling path.

Captioning failures are isolated: a single image that errors is logged at
WARNING and dropped; the document still ingests with text + remaining
captions. Encrypted / corrupt PDFs return an empty caption list rather than
raising, so the text path continues to work.

LLM and config imports are lazy (inside the functions that need them) so
this module can be unit-tested without resolving the full observability +
LiteLLM client stack.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, NamedTuple

import fitz  # PyMuPDF

_log = logging.getLogger(__name__)


CAPTION_SYSTEM_PROMPT = (
    "Describe this image in detail. If it is a person, describe their "
    "appearance, clothing, hair, and posture. Keep it concise."
)


class PageCaptions(NamedTuple):
    """Captions emitted for a single PDF page (0-indexed)."""

    page: int
    captions: list[str]


@dataclass(frozen=True)
class _ImageBlob:
    page: int
    xref: int
    data: bytes
    ext: str
    width: int
    height: int


@dataclass(frozen=True)
class _Limits:
    max_images: int
    concurrency: int
    caption_max_tokens: int
    min_dimension: int
    min_bytes: int
    vision_model: str


def _load_limits() -> _Limits:
    """Resolve config at call time so the module imports cheaply.

    Falls back to env vars if ``rag.config`` cannot be imported (e.g. unit
    tests without pydantic-settings installed). Test code can also
    monkeypatch this function directly.
    """

    try:
        from rag.config import settings

        return _Limits(
            max_images=settings.vision_pdf_max_images,
            concurrency=settings.vision_pdf_concurrency,
            caption_max_tokens=settings.vision_pdf_caption_max_tokens,
            min_dimension=settings.vision_pdf_min_dimension,
            min_bytes=settings.vision_pdf_min_bytes,
            vision_model=settings.vision_model,
        )
    except Exception:  # noqa: BLE001 — fall back to env vars
        return _Limits(
            max_images=int(os.environ.get("VISION_PDF_MAX_IMAGES", "20")),
            concurrency=int(os.environ.get("VISION_PDF_CONCURRENCY", "4")),
            caption_max_tokens=int(
                os.environ.get("VISION_PDF_CAPTION_MAX_TOKENS", "256")
            ),
            min_dimension=int(os.environ.get("VISION_PDF_MIN_DIMENSION", "64")),
            min_bytes=int(os.environ.get("VISION_PDF_MIN_BYTES", "2048")),
            vision_model=os.environ.get("VISION_MODEL", "groq-llama-4-scout"),
        )


async def _invoke_vision_llm(
    messages: list[dict[str, Any]], *, model: str, max_tokens: int
) -> str:
    """Lazy wrapper around ``chat_complete``.

    Importing ``rag.orchestrator.llm`` pulls the langfuse + OTEL stack;
    we want unit tests of this module to skip that entirely by
    monkeypatching this function.
    """

    from rag.orchestrator.llm import chat_complete

    result = await chat_complete(
        messages,
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        timeout_seconds=20.0,
        record_observability=False,
    )
    return (result.content or "").strip()


def _llm_error_class() -> type[BaseException]:
    """Best-effort import of ``LLMError`` for narrow ``except`` clauses."""

    try:
        from rag.orchestrator.llm import LLMError

        return LLMError
    except Exception:  # noqa: BLE001 — fall back to a broad sentinel
        return RuntimeError


def _collect_blobs(path: str, limits: _Limits) -> list[_ImageBlob]:
    """Open the PDF and pull embedded image blobs subject to filters.

    Returns ``[]`` on any fitz error (encrypted / corrupt PDFs included).
    Synchronous; callers should wrap in ``asyncio.to_thread``.
    """

    try:
        doc = fitz.open(path)
    except (fitz.FileDataError, RuntimeError) as exc:
        _log.warning("vision_pdf: fitz.open failed for %s: %s", path, exc)
        return []
    except Exception as exc:  # noqa: BLE001 — fitz raises various opaque errors
        _log.warning("vision_pdf: unexpected fitz error for %s: %s", path, exc)
        return []

    collected: list[_ImageBlob] = []
    try:
        for page_index, page in enumerate(doc):
            if len(collected) >= limits.max_images:
                break
            try:
                images = page.get_images(full=True)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "vision_pdf: get_images failed on page %d of %s: %s",
                    page_index,
                    path,
                    exc,
                )
                continue
            for img_meta in images:
                if len(collected) >= limits.max_images:
                    break
                xref = img_meta[0]
                try:
                    extracted = doc.extract_image(xref)
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "vision_pdf: extract_image(xref=%d) failed: %s", xref, exc
                    )
                    continue
                data: bytes = extracted.get("image") or b""
                width = int(extracted.get("width") or 0)
                height = int(extracted.get("height") or 0)
                ext = str(extracted.get("ext") or "png").lower()
                if (
                    width < limits.min_dimension
                    or height < limits.min_dimension
                    or len(data) < limits.min_bytes
                ):
                    continue
                collected.append(
                    _ImageBlob(
                        page=page_index,
                        xref=xref,
                        data=data,
                        ext=ext,
                        width=width,
                        height=height,
                    )
                )
    finally:
        doc.close()
    return collected


async def _caption_one(
    blob: _ImageBlob,
    semaphore: asyncio.Semaphore,
    limits: _Limits,
    llm_error_cls: type[BaseException],
) -> str | None:
    """Caption a single image blob. Returns ``None`` on any failure."""

    data_uri = (
        f"data:image/{blob.ext};base64,{base64.b64encode(blob.data).decode('ascii')}"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        },
    ]
    async with semaphore:
        try:
            text = await _invoke_vision_llm(
                messages,
                model=limits.vision_model,
                max_tokens=limits.caption_max_tokens,
            )
        except llm_error_cls as exc:
            _log.warning(
                "vision_pdf: caption failed (xref=%d, page=%d): %s",
                blob.xref,
                blob.page,
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — vision must never break ingest
            _log.warning(
                "vision_pdf: caption raised unexpectedly (xref=%d, page=%d): %s",
                blob.xref,
                blob.page,
                exc,
            )
            return None
    return text or None


async def extract_pdf_captions(path: str) -> list[PageCaptions]:
    """Extract per-page captions from a PDF.

    Returns one :class:`PageCaptions` per page that produced ≥1 caption.
    Pages with no surviving captions are omitted (caller can iterate freely
    without ``None`` checks). On unreadable PDFs, returns ``[]``.
    """

    limits = _load_limits()
    blobs = await asyncio.to_thread(_collect_blobs, path, limits)
    if not blobs:
        return []

    llm_error_cls = _llm_error_class()
    semaphore = asyncio.Semaphore(limits.concurrency)
    captions = await asyncio.gather(
        *(_caption_one(b, semaphore, limits, llm_error_cls) for b in blobs)
    )

    per_page: dict[int, list[str]] = {}
    for blob, caption in zip(blobs, captions, strict=True):
        if caption is None:
            continue
        per_page.setdefault(blob.page, []).append(caption)

    return [
        PageCaptions(page=page, captions=caps)
        for page, caps in sorted(per_page.items())
    ]


def _merge_text_and_captions(
    text_pages: list[str], page_captions: list[PageCaptions]
) -> str:
    """Interleave per-page text with caption lines.

    Pages without text but with captions are emitted (scanned-PDF path).
    Pages with neither are dropped.
    """

    captions_by_page = {pc.page: pc.captions for pc in page_captions}
    total_pages = max(
        len(text_pages),
        (max(captions_by_page) + 1) if captions_by_page else 0,
    )

    blocks: list[str] = []
    for i in range(total_pages):
        text = text_pages[i].strip() if i < len(text_pages) else ""
        caps = captions_by_page.get(i, [])
        parts: list[str] = []
        if text:
            parts.append(text)
        parts.extend(f"[Image Description: {c}]" for c in caps)
        if parts:
            blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def _read_text_pages(path: str) -> list[str]:
    """Per-page text via pypdf (sync). Wrap in ``asyncio.to_thread``."""

    from pypdf import PdfReader

    reader = PdfReader(path)
    return [(page.extract_text() or "").strip() for page in reader.pages]


async def caption_pdf_for_upload(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract text + vision captions for an uploaded PDF.

    Returns ``(merged_body, caption_count)``. ``merged_body`` interleaves
    page text with ``[Image Description: ...]`` lines. ``caption_count`` is
    the number of caption lines emitted — callers can use it to decide
    whether a captions-only body is acceptable (scanned PDF path).
    """

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(pdf_bytes)
        tmp.close()
        text_pages, page_captions = await asyncio.gather(
            asyncio.to_thread(_read_text_pages, tmp.name),
            extract_pdf_captions(tmp.name),
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    body = _merge_text_and_captions(text_pages, page_captions)
    caption_count = sum(len(pc.captions) for pc in page_captions)
    return body, caption_count


def format_caption_appendix(page_captions: list[PageCaptions]) -> str:
    """Render captions as an ``## Image Descriptions`` block for v2 path.

    Returns an empty string if no captions. Used by ingest_v2/multimodal to
    append captions after Docling-emitted Markdown without disturbing
    Docling's structural output.
    """

    if not page_captions:
        return ""
    lines = ["## Image Descriptions", ""]
    for pc in page_captions:
        lines.append(f"### Page {pc.page + 1}")
        for caption in pc.captions:
            lines.append(f"- [Image Description: {caption}]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
