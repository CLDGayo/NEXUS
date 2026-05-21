"""Multimodal document parsing via Docling.

Converts PDFs, DOCX, PPTX, HTML, images, and (pass-through) Markdown to a
single normalized Markdown string. Table structure, headings, lists, and
fenced code blocks are preserved so downstream semantic boundary detection
can see the same structure a human reader sees.

Docling is imported lazily so unit tests can mock the converter without
installing torch + the heavy parsing stack.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from rag.config import settings

_log = logging.getLogger(__name__)

# Extensions that bypass Docling — Markdown is already structured.
_PASSTHROUGH_EXT: frozenset[str] = frozenset({".md", ".markdown"})

# Extensions Docling can parse.
_DOCLING_EXT: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
    }
)


class ConverterProtocol(Protocol):
    """Subset of Docling ``DocumentConverter`` used by this module.

    Declared so tests can pass a stub without depending on Docling itself.
    """

    def convert(self, source: str) -> object: ...


def _load_docling_converter() -> ConverterProtocol:
    """Import + construct Docling. Lazy so cold-path callers don't pay."""

    from docling.document_converter import DocumentConverter

    return DocumentConverter()


_converter: ConverterProtocol | None = None


def get_converter() -> ConverterProtocol:
    """Process-wide singleton. Resets via :func:`set_converter`."""

    global _converter
    if _converter is None:
        _converter = _load_docling_converter()
    return _converter


def set_converter(converter: ConverterProtocol | None) -> None:
    """Test hook — inject a stub or clear the cache."""

    global _converter
    _converter = converter


class UnsupportedFormatError(ValueError):
    pass


def parse_to_markdown(path: Path) -> str:
    """Return clean Markdown for ``path``.

    Markdown files are read verbatim (Docling would re-emit identically but
    we skip the round-trip). Every other supported format flows through
    Docling's ``DocumentConverter``.

    Raises ``UnsupportedFormatError`` for unknown extensions so the caller
    can surface a specific error rather than silently producing empty text.
    """

    suffix = path.suffix.lower()

    if suffix in _PASSTHROUGH_EXT:
        return path.read_text(encoding="utf-8")

    if suffix not in _DOCLING_EXT:
        raise UnsupportedFormatError(
            f"no parser registered for extension {suffix!r} (path: {path})"
        )

    converter = get_converter()
    result = converter.convert(str(path))

    # Docling >= 2.x exposes `.document.export_to_markdown()`. We try a few
    # shapes so version drift doesn't immediately break us.
    document = getattr(result, "document", result)
    for attr in ("export_to_markdown", "to_markdown", "markdown"):
        emit = getattr(document, attr, None)
        if callable(emit):
            return emit()
        if isinstance(emit, str):
            return emit

    raise RuntimeError(f"docling result for {path} exposed no markdown export method")


async def parse_to_markdown_with_vision(path: Path) -> str:
    """Async variant that appends vision captions for PDFs (Phase 16).

    Equivalent to :func:`parse_to_markdown` when
    ``settings.vision_pdf_v2_enabled`` is False (default) — Docling output
    is returned verbatim. When enabled and ``path`` is a PDF, embedded
    images are extracted via PyMuPDF, captioned via the vision LLM, and
    appended as a trailing ``## Image Descriptions`` block. Failures are
    logged and the un-augmented Markdown is returned.
    """

    markdown = await asyncio.to_thread(parse_to_markdown, path)
    if not settings.vision_pdf_v2_enabled:
        return markdown
    if path.suffix.lower() != ".pdf":
        return markdown
    try:
        # Lazy import — keeps the heavy LLM/httpx stack off the import path
        # for callers that never enable vision.
        from rag.vision_pdf import extract_pdf_captions, format_caption_appendix

        page_captions = await extract_pdf_captions(str(path))
        appendix = format_caption_appendix(page_captions)
    except Exception as exc:  # noqa: BLE001 — never break ingest
        _log.warning("vision_pdf: v2 captioning failed for %s: %s", path, exc)
        return markdown
    if not appendix:
        return markdown
    return f"{markdown.rstrip()}\n\n{appendix}"
