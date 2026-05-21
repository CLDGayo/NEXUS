"""Pin the fastembed cross-encoder import path against future dep drift.

2026-05-21: `fastembed` >=0.4 moved `TextCrossEncoder` to a subpackage and
the bare `from fastembed import TextCrossEncoder` broke silently. Prod's
``rag/retrieval/rerank.py::get_cross_encoder`` swallowed the ImportError
inside a generic ``except Exception``, dropped to RRF order, and shipped
noisier top-K into the guardrail layer — which then blocked greetings.
"""

from __future__ import annotations

import pytest

from rag.retrieval.rerank import _load_cross_encoder_cls, reranker_import_probe


class TestImportResolution:
    """The resolver must find the class on the installed fastembed."""

    def test_load_returns_a_class(self) -> None:
        cls = _load_cross_encoder_cls()
        assert isinstance(cls, type)
        assert "TextCrossEncoder" in cls.__qualname__

    def test_module_path_is_subpackage_form(self) -> None:
        # Locks in the modern path. If a future fastembed moves it again,
        # this test fails noisily instead of dropping to RRF in prod.
        cls = _load_cross_encoder_cls()
        assert "rerank" in cls.__module__ or cls.__module__ == "fastembed"


class TestImportProbe:
    """The /health/reranker endpoint calls this."""

    def test_probe_reports_ok_with_current_install(self) -> None:
        report = reranker_import_probe()
        assert report["ok"] is True
        assert "import_path" in report
        assert report["model"]  # config.rerank_model is non-empty

    def test_probe_reports_failure_when_neither_path_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate both import paths failing — patch the loader directly
        # because reaching into sys.modules to fake-break fastembed at
        # runtime is brittle and version-coupled.
        from rag.retrieval import rerank as rerank_mod

        def _raise() -> object:
            raise ImportError("simulated double-failure")

        monkeypatch.setattr(rerank_mod, "_load_cross_encoder_cls", _raise)
        report = rerank_mod.reranker_import_probe()
        assert report["ok"] is False
        assert "simulated double-failure" in report["error"]
