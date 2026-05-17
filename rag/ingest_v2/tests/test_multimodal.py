"""Phase 4 multimodal parser tests.

Docling is mocked. Markdown passthrough and unsupported-format paths run
without the dependency installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingest_v2 import multimodal


class _StubConverter:
    def __init__(self, markdown: str) -> None:
        self._markdown = markdown
        self.calls: list[str] = []

    def convert(self, source: str) -> object:
        self.calls.append(source)
        class _Document:
            def __init__(self, text: str) -> None:
                self._text = text

            def export_to_markdown(self) -> str:
                return self._text

        class _Result:
            def __init__(self, text: str) -> None:
                self.document = _Document(text)

        return _Result(self._markdown)


@pytest.fixture(autouse=True)
def reset_converter() -> None:
    multimodal.set_converter(None)
    yield
    multimodal.set_converter(None)


@pytest.mark.unit
class TestPassthrough:
    def test_markdown_is_read_verbatim(self, tmp_path: Path) -> None:
        path = tmp_path / "note.md"
        path.write_text("# Hello\n\nbody")
        assert multimodal.parse_to_markdown(path) == "# Hello\n\nbody"

    def test_markdown_extension_uppercase(self, tmp_path: Path) -> None:
        path = tmp_path / "note.MARKDOWN"
        path.write_text("hi")
        assert multimodal.parse_to_markdown(path) == "hi"


@pytest.mark.unit
class TestUnsupported:
    def test_unknown_extension_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "weird.xyz"
        path.write_text("")
        with pytest.raises(multimodal.UnsupportedFormatError):
            multimodal.parse_to_markdown(path)


@pytest.mark.unit
class TestDoclingStub:
    def test_pdf_via_stub_converter(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.pdf"
        path.write_bytes(b"fake pdf bytes")

        stub = _StubConverter(markdown="# Stubbed\n\nfrom pdf")
        multimodal.set_converter(stub)

        result = multimodal.parse_to_markdown(path)
        assert result == "# Stubbed\n\nfrom pdf"
        assert stub.calls == [str(path)]

    def test_pptx_via_stub_converter(self, tmp_path: Path) -> None:
        path = tmp_path / "deck.pptx"
        path.write_bytes(b"x")
        multimodal.set_converter(_StubConverter(markdown="slides"))
        assert multimodal.parse_to_markdown(path) == "slides"
