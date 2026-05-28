"""Phase 31 — Qdrant leak scrubber classifier."""

from __future__ import annotations

from rag.scripts.cleanup_phase31_leak import _is_leak_payload


def test_clean_payload_returns_none() -> None:
    assert (
        _is_leak_payload({"tenant_id": "hunter", "file": "Notes/foo.md"})
        is None
    )


def test_missing_payload_classified() -> None:
    assert _is_leak_payload(None) == "missing_payload"


def test_missing_tenant_classified() -> None:
    assert _is_leak_payload({"file": "Notes/foo.md"}) == "missing_tenant_id"
    assert (
        _is_leak_payload({"tenant_id": "", "file": "x.md"})
        == "missing_tenant_id"
    )


def test_dotvenv_at_root() -> None:
    assert (
        _is_leak_payload({"tenant_id": "hunter", "file": ".venv/lib/site.py"})
        == "leaked_source_tree"
    )


def test_dotvenv_nested() -> None:
    assert (
        _is_leak_payload(
            {"tenant_id": "hunter", "file": "rag/.venv/lib/site.py"}
        )
        == "leaked_source_tree"
    )


def test_pycache_classified() -> None:
    assert (
        _is_leak_payload(
            {"tenant_id": "hunter", "file": "rag/routers/__pycache__/x.pyc"}
        )
        == "leaked_source_tree"
    )


def test_node_modules_classified() -> None:
    assert (
        _is_leak_payload(
            {"tenant_id": "hunter", "file": "nexus-ui/node_modules/react.js"}
        )
        == "leaked_source_tree"
    )


def test_lookalike_name_not_classified() -> None:
    # "venvironment" should not match — the regex requires a path
    # boundary on both sides of the literal segment.
    assert (
        _is_leak_payload(
            {"tenant_id": "hunter", "file": "Notes/venvironment.md"}
        )
        is None
    )
    assert (
        _is_leak_payload(
            {"tenant_id": "hunter", "file": "Notes/my-node_modules-rant.md"}
        )
        is None
    )
