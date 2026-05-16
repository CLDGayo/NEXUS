"""Unit tests for the upgraded query engine.

Covers source dedup, display-name cleaning, numbered context formatting,
the strict citation system prompt, and follow-up parsing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from query import (
    Chunk,
    DocumentSource,
    Source,
    SYSTEM_PROMPT,
    _parse_followups,
    _source_to_dict,
    build_messages,
    dedupe_sources,
    display_name,
    format_context,
    generate_followups,
)


# ── display_name ─────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("path,expected", [
    ("00 - Inbox/Clyde - New Enhanced CV.md", "Clyde - New Enhanced CV"),
    ("Notes.md", "Notes"),
    ("a/b/c/d.md", "d"),
    ("no-extension", "no-extension"),
    ("nested/deep/path/Concept Page.md", "Concept Page"),
])
def test_display_name_strips_path_and_extension(path: str, expected: str) -> None:
    assert display_name(path) == expected


# ── dedupe_sources ───────────────────────────────────────


@pytest.mark.unit
def test_dedupe_sources_groups_by_file_and_preserves_order() -> None:
    raw = [
        Source(file="A.md", heading="h1", score=0.9, text="t1"),
        Source(file="B.md", heading="h1", score=0.8, text="t2"),
        Source(file="A.md", heading="h2", score=0.7, text="t3"),
        Source(file="A.md", heading="h3", score=0.95, text="t4"),
    ]
    out = dedupe_sources(raw)

    assert [d.index for d in out] == [1, 2]
    assert [d.file for d in out] == ["A.md", "B.md"]
    assert len(out[0].chunks) == 3
    assert out[0].chunks[0].score == 0.95  # sorted score-desc
    assert out[0].chunks[-1].score == 0.7
    assert out[0].display == "A"


@pytest.mark.unit
def test_dedupe_sources_empty_returns_empty() -> None:
    assert dedupe_sources([]) == []


# ── format_context ───────────────────────────────────────


@pytest.mark.unit
def test_format_context_uses_numbered_source_format() -> None:
    sources = [
        DocumentSource(
            index=1,
            file="00 - Inbox/CV.md",
            display="CV",
            chunks=[Chunk(heading="h", score=0.9, text="body of cv")],
        ),
        DocumentSource(
            index=2,
            file="Notes/Plan.md",
            display="Plan",
            chunks=[
                Chunk(heading="a", score=0.8, text="part one"),
                Chunk(heading="b", score=0.7, text="part two"),
            ],
        ),
    ]
    ctx = format_context(sources)

    assert "Source [1]: CV" in ctx
    assert "Source [2]: Plan" in ctx
    assert "Content: body of cv" in ctx
    assert "part one\n\npart two" in ctx
    # Strict: never leak raw paths or extensions into the LLM context
    assert "00 - Inbox" not in ctx
    assert "Notes/Plan.md" not in ctx
    assert ".md" not in ctx


# ── SYSTEM_PROMPT ────────────────────────────────────────


@pytest.mark.unit
def test_system_prompt_forbids_raw_paths_and_requires_numbered_citations() -> None:
    # Numbered-citation rule is explicit.
    assert "[1]" in SYSTEM_PROMPT
    # The prompt prohibits raw paths / file names / extensions / [Note:...] format.
    assert "NEVER" in SYSTEM_PROMPT
    assert ".md" in SYSTEM_PROMPT
    assert "[Note:" in SYSTEM_PROMPT  # listed as forbidden, not used as a directive
    # The legacy directive ("Cite sources using the format [Note: filename]") is gone.
    assert "format [Note:" not in SYSTEM_PROMPT


# ── build_messages ───────────────────────────────────────


@pytest.mark.unit
def test_build_messages_includes_system_history_and_context() -> None:
    history = [
        {"role": "user", "content": "earlier q"},
        {"role": "assistant", "content": "earlier a"},
    ]
    msgs = build_messages("what now?", "Source [1]: X\nContent: y", history)

    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert msgs[1] == history[0]
    assert msgs[2] == history[1]
    assert msgs[-1]["role"] == "user"
    assert "Source [1]: X" in msgs[-1]["content"]
    assert "Question: what now?" in msgs[-1]["content"]


@pytest.mark.unit
def test_build_messages_trims_history_to_last_six() -> None:
    history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    msgs = build_messages("q", "ctx", history)
    assert len(msgs) == 1 + 6 + 1  # system + last 6 + user
    assert msgs[1]["content"] == "msg4"  # first kept entry is index 4


# ── _source_to_dict ──────────────────────────────────────


@pytest.mark.unit
def test_source_to_dict_serializes_full_shape() -> None:
    ds = DocumentSource(
        index=1,
        file="A.md",
        display="A",
        chunks=[Chunk(heading="h", score=0.81234, text="body")],
    )
    out = _source_to_dict(ds)
    assert out["index"] == 1
    assert out["file"] == "A.md"
    assert out["display"] == "A"
    assert out["chunks"][0] == {"heading": "h", "score": 0.812, "text": "body"}


# ── _parse_followups ─────────────────────────────────────


@pytest.mark.unit
def test_parse_followups_prefers_json_array() -> None:
    raw = '["What about X?", "How does Y compare?", "When should I use Z?"]'
    assert _parse_followups(raw) == [
        "What about X?",
        "How does Y compare?",
        "When should I use Z?",
    ]


@pytest.mark.unit
def test_parse_followups_caps_at_three() -> None:
    raw = '["a","b","c","d","e"]'
    assert _parse_followups(raw) == ["a", "b", "c"]


@pytest.mark.unit
def test_parse_followups_falls_back_to_line_splitting() -> None:
    raw = """1. First question?
    2) Second question?
    - Third question?"""
    assert _parse_followups(raw) == [
        "First question?",
        "Second question?",
        "Third question?",
    ]


@pytest.mark.unit
def test_parse_followups_handles_garbage() -> None:
    assert _parse_followups("") == []
    assert _parse_followups("   ") == []


# ── generate_followups ───────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_followups_returns_three_strings_on_valid_response() -> None:
    fake_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content='["Q1?", "Q2?", "Q3?"]'
        ))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=fake_resp))
        )
    )
    with patch("query.AsyncGroq", return_value=fake_client):
        result = await generate_followups("question", "answer text")
    assert result == ["Q1?", "Q2?", "Q3?"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_followups_returns_empty_on_groq_error() -> None:
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
        )
    )
    with patch("query.AsyncGroq", return_value=fake_client):
        result = await generate_followups("q", "a")
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_followups_skips_when_answer_empty() -> None:
    # Should short-circuit without calling Groq at all.
    with patch("query.AsyncGroq") as mock_groq:
        result = await generate_followups("q", "   ")
    assert result == []
    mock_groq.assert_not_called()
