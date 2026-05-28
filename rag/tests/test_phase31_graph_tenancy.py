"""Phase 31 — graph layer rewrites: nexus_graph.db gone, tenant_id required."""

from __future__ import annotations

import ast
import inspect

from rag.ingest_v2 import graph_db, graph_index
from rag.retrieval import graph as graph_retrieval


def _strip_docstrings(src: str) -> str:
    """Return ``src`` with every module/class/function docstring removed."""

    tree = ast.parse(src)
    lines = src.splitlines()
    drop: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    drop.add(ln)
    kept = [
        line for i, line in enumerate(lines, start=1) if i not in drop
    ]
    return "\n".join(kept)


def test_graph_db_no_longer_imports_aiosqlite() -> None:
    src = inspect.getsource(graph_db)
    assert "aiosqlite" not in src, (
        "Phase 31: graph_db must not import aiosqlite; "
        "nexus_graph.db is eradicated."
    )
    code_only = _strip_docstrings(src)
    assert "nexus_graph.db" not in code_only
    assert "NEXUS_GRAPH_DB" not in code_only
    assert "sqlite" not in code_only.lower()


def test_graph_index_no_longer_imports_aiosqlite() -> None:
    src = inspect.getsource(graph_index)
    assert "aiosqlite" not in src


def test_graph_retrieval_no_longer_imports_aiosqlite() -> None:
    src = inspect.getsource(graph_retrieval)
    assert "aiosqlite" not in src


def test_index_file_links_requires_tenant_id() -> None:
    sig = inspect.signature(graph_index.index_file_links)
    assert "tenant_id" in sig.parameters, (
        "index_file_links must accept tenant_id"
    )
    # keyword-only and required
    param = sig.parameters["tenant_id"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


def test_resolve_link_targets_requires_tenant_id() -> None:
    sig = inspect.signature(graph_db.resolve_link_targets)
    assert "tenant_id" in sig.parameters
    assert (
        sig.parameters["tenant_id"].default is inspect.Parameter.empty
    )


def test_fetch_note_titles_requires_tenant_id() -> None:
    sig = inspect.signature(graph_db.fetch_note_titles)
    assert "tenant_id" in sig.parameters
    assert (
        sig.parameters["tenant_id"].default is inspect.Parameter.empty
    )


def test_neighbors_of_requires_tenant_id() -> None:
    sig = inspect.signature(graph_db.neighbors_of)
    assert "tenant_id" in sig.parameters
    assert (
        sig.parameters["tenant_id"].default is inspect.Parameter.empty
    )


def test_pipeline_ingest_file_requires_tenant_id_and_slug() -> None:
    from rag.ingest_v2.pipeline import ingest_file

    sig = inspect.signature(ingest_file)
    assert "tenant_id" in sig.parameters
    assert "tenant_slug" in sig.parameters
    assert (
        sig.parameters["tenant_id"].default is inspect.Parameter.empty
    )
    assert (
        sig.parameters["tenant_slug"].default is inspect.Parameter.empty
    )


def test_pipeline_skip_dirs_includes_python_artifacts() -> None:
    from rag.ingest_v2.pipeline import _VAULT_SKIP_DIRS

    for required in (".venv", "__pycache__", "node_modules"):
        assert required in _VAULT_SKIP_DIRS, (
            f"Phase 31: pipeline must skip {required}"
        )


def test_documents_router_skip_set_includes_python_artifacts() -> None:
    from rag.routers.documents import _SKIP

    for required in (".venv", "__pycache__"):
        assert required in _SKIP, (
            f"Phase 31: documents router _SKIP must include {required}"
        )
