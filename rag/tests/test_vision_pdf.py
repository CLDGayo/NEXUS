"""Unit tests for Phase 16 PDF image captioning.

PyMuPDF (``fitz``) and the vision LLM are both stubbed so the tests run
without a real PDF and without hitting LiteLLM. The module under test
(:mod:`vision_pdf`) uses lazy imports for ``rag.config`` and
``rag.orchestrator.llm`` so the module is importable in lightweight
environments; tests monkeypatch ``_load_limits`` and ``_invoke_vision_llm``
directly.

Run from the rag/ directory:
    uv run --with pytest --with pytest-asyncio pytest tests/test_vision_pdf.py -v
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

import vision_pdf


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakePage:
    def __init__(self, images_meta: list[tuple]) -> None:
        self._images_meta = images_meta

    def get_images(self, full: bool = False) -> list[tuple]:  # noqa: ARG002
        return list(self._images_meta)


class _FakeDoc:
    def __init__(
        self,
        pages: list[_FakePage],
        blobs: dict[int, dict[str, Any]],
    ) -> None:
        self._pages = pages
        self._blobs = blobs
        self.closed = False

    def __iter__(self) -> Iterator[_FakePage]:
        return iter(self._pages)

    def extract_image(self, xref: int) -> dict[str, Any]:
        return self._blobs[xref]

    def close(self) -> None:
        self.closed = True


def _make_blob(
    *,
    data: bytes = b"\x89PNG" + b"\x00" * 4096,
    ext: str = "png",
    width: int = 200,
    height: int = 200,
) -> dict[str, Any]:
    return {"image": data, "ext": ext, "width": width, "height": height}


def _install_fitz_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pages: list[list[int]],
    blobs: dict[int, dict[str, Any]],
) -> _FakeDoc:
    """``pages[i]`` lists the xref ints on page ``i``."""
    fake_pages = [
        _FakePage([(xref, 0, 0, 0, 0, "", "", "", "") for xref in xrefs])
        for xrefs in pages
    ]
    doc = _FakeDoc(fake_pages, blobs)
    monkeypatch.setattr(vision_pdf.fitz, "open", lambda _path: doc)
    return doc


def _set_limits(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_images: int = 20,
    concurrency: int = 4,
    caption_max_tokens: int = 256,
    min_dimension: int = 64,
    min_bytes: int = 2048,
    vision_model: str = "test-vision-model",
) -> None:
    limits = vision_pdf._Limits(
        max_images=max_images,
        concurrency=concurrency,
        caption_max_tokens=caption_max_tokens,
        min_dimension=min_dimension,
        min_bytes=min_bytes,
        vision_model=vision_model,
    )
    monkeypatch.setattr(vision_pdf, "_load_limits", lambda: limits)


class _FakeLLMError(RuntimeError):
    pass


def _install_llm_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: str = "a person in a black blazer",
    raises: type[BaseException] | None = None,
) -> list[list[dict[str, Any]]]:
    """Replace ``_invoke_vision_llm`` with an async stub. Returns the call log."""
    calls: list[list[dict[str, Any]]] = []

    async def _fake_invoke(
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,  # noqa: ARG001
    ) -> str:
        calls.append(messages)
        if raises is not None:
            raise raises("simulated failure")
        return response

    monkeypatch.setattr(vision_pdf, "_invoke_vision_llm", _fake_invoke)
    monkeypatch.setattr(vision_pdf, "_llm_error_class", lambda: _FakeLLMError)
    return calls


# ---------------------------------------------------------------------------
# extract_pdf_captions
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_images_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(monkeypatch, pages=[[], []], blobs={})
    calls = _install_llm_stub(monkeypatch)

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    assert result == []
    assert calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_captions_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch)
    blobs = {1: _make_blob(), 2: _make_blob()}
    _install_fitz_stub(monkeypatch, pages=[[1], [2]], blobs=blobs)
    _install_llm_stub(monkeypatch, response="a dog")

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    assert [pc.page for pc in result] == [0, 1]
    assert all(pc.captions == ["a dog"] for pc in result)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_caption_failure_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(monkeypatch, pages=[[1]], blobs={1: _make_blob()})
    _install_llm_stub(monkeypatch, raises=_FakeLLMError)

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    # LLM error on the sole image → no captions, no raise.
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_exception_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(monkeypatch, pages=[[1]], blobs={1: _make_blob()})
    _install_llm_stub(monkeypatch, raises=ValueError)

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    # Even a non-LLMError exception must be swallowed — vision never breaks ingest.
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_small_images_filtered_pre_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)
    tiny = _make_blob(width=32, height=32)
    big = _make_blob(width=300, height=300)
    _install_fitz_stub(monkeypatch, pages=[[1, 2]], blobs={1: tiny, 2: big})
    calls = _install_llm_stub(monkeypatch, response="ok")

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    # Only the big image should reach the LLM.
    assert len(calls) == 1
    assert result == [vision_pdf.PageCaptions(page=0, captions=["ok"])]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tiny_bytes_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch)
    thin = _make_blob(data=b"\x00" * 500)  # under 2KB default
    _install_fitz_stub(monkeypatch, pages=[[1]], blobs={1: thin})
    calls = _install_llm_stub(monkeypatch)

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    assert calls == []
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_global_image_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch, max_images=5)
    pages = [list(range(1, 31))]  # 30 images on one page
    blobs = {i: _make_blob() for i in range(1, 31)}
    _install_fitz_stub(monkeypatch, pages=pages, blobs=blobs)
    calls = _install_llm_stub(monkeypatch, response="x")

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    assert len(calls) == 5
    assert sum(len(pc.captions) for pc in result) == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrency_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_limits(monkeypatch, concurrency=3)
    pages = [list(range(1, 11))]
    blobs = {i: _make_blob() for i in range(1, 11)}
    _install_fitz_stub(monkeypatch, pages=pages, blobs=blobs)
    monkeypatch.setattr(vision_pdf, "_llm_error_class", lambda: _FakeLLMError)

    inflight = {"now": 0, "peak": 0}

    async def _tracked(
        _messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,  # noqa: ARG001
    ) -> str:
        inflight["now"] += 1
        inflight["peak"] = max(inflight["peak"], inflight["now"])
        await asyncio.sleep(0.02)
        inflight["now"] -= 1
        return "x"

    monkeypatch.setattr(vision_pdf, "_invoke_vision_llm", _tracked)

    await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")
    assert inflight["peak"] <= 3
    assert inflight["peak"] >= 1  # sanity: stuff actually ran


@pytest.mark.unit
@pytest.mark.asyncio
async def test_encrypted_pdf_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)

    def _boom(_path: str) -> _FakeDoc:
        raise vision_pdf.fitz.FileDataError("encrypted")

    monkeypatch.setattr(vision_pdf.fitz, "open", _boom)
    calls = _install_llm_stub(monkeypatch)

    result = await vision_pdf.extract_pdf_captions("/tmp/fake.pdf")

    assert result == []
    assert calls == []


# ---------------------------------------------------------------------------
# caption_pdf_for_upload
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_interleaves_captions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(
        monkeypatch, pages=[[1], [2]], blobs={1: _make_blob(), 2: _make_blob()}
    )
    _install_llm_stub(monkeypatch, response="a face")
    monkeypatch.setattr(
        vision_pdf,
        "_read_text_pages",
        lambda _path: ["Page one text", "Page two text"],
    )

    body, count = await vision_pdf.caption_pdf_for_upload(b"%PDF-1.4 fake")

    assert count == 2
    assert body == (
        "Page one text\n\n[Image Description: a face]\n\n"
        "Page two text\n\n[Image Description: a face]"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_scanned_pdf_captions_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(monkeypatch, pages=[[1]], blobs={1: _make_blob()})
    _install_llm_stub(monkeypatch, response="headshot")
    monkeypatch.setattr(vision_pdf, "_read_text_pages", lambda _path: [""])

    body, count = await vision_pdf.caption_pdf_for_upload(b"%PDF-1.4 scanned")

    assert count == 1
    assert body == "[Image Description: headshot]"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_no_text_no_captions_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_limits(monkeypatch)
    _install_fitz_stub(monkeypatch, pages=[[]], blobs={})
    _install_llm_stub(monkeypatch)
    monkeypatch.setattr(vision_pdf, "_read_text_pages", lambda _path: [""])

    body, count = await vision_pdf.caption_pdf_for_upload(b"%PDF-1.4 empty")

    assert body == ""
    assert count == 0


# ---------------------------------------------------------------------------
# format_caption_appendix
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_caption_appendix_empty() -> None:
    assert vision_pdf.format_caption_appendix([]) == ""


@pytest.mark.unit
def test_format_caption_appendix_shape() -> None:
    pcs = [
        vision_pdf.PageCaptions(page=0, captions=["a cat"]),
        vision_pdf.PageCaptions(page=2, captions=["a logo", "a chart"]),
    ]
    out = vision_pdf.format_caption_appendix(pcs)
    assert out.startswith("## Image Descriptions")
    assert "### Page 1" in out
    assert "### Page 3" in out
    assert "- [Image Description: a cat]" in out
    assert "- [Image Description: a logo]" in out
    assert "- [Image Description: a chart]" in out


# ---------------------------------------------------------------------------
# _load_limits fallback (env-based) — verifies the lightweight path works
# without pydantic-settings installed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_limits_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the rag.config import to fail by clearing sys.modules entries.
    import sys

    monkeypatch.setitem(sys.modules, "rag.config", None)
    monkeypatch.setenv("VISION_PDF_MAX_IMAGES", "7")
    monkeypatch.setenv("VISION_PDF_CONCURRENCY", "2")
    monkeypatch.setenv("VISION_MODEL", "env-model")

    limits = vision_pdf._load_limits()
    assert limits.max_images == 7
    assert limits.concurrency == 2
    assert limits.vision_model == "env-model"
