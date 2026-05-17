"""Phase 5 diagnose CLI tests.

The full reachability calls touch network; here we just verify that the
in-process logic produces structured results, distinguishes the configured
vs unconfigured Langfuse path, and that ``run()`` returns the right exit
code under each combination.
"""

from __future__ import annotations

import pytest

from rag.observability import diagnose


@pytest.mark.unit
class TestLangfuseSmoke:
    def test_missing_keys_returns_clear_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from rag.observability import diagnose as diag

        monkeypatch.setattr(diag.settings, "langfuse_public_key", None, raising=False)
        monkeypatch.setattr(diag.settings, "langfuse_secret_key", None, raising=False)
        result = diag._langfuse_smoke()
        assert not result.ok
        assert "LANGFUSE_PUBLIC_KEY" in result.detail


@pytest.mark.unit
def test_run_returns_nonzero_when_any_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        diagnose,
        "_otel_smoke",
        lambda: diagnose.DiagnoseResult(surface="otel", ok=True, detail="ok"),
    )
    monkeypatch.setattr(
        diagnose,
        "_langfuse_smoke",
        lambda: diagnose.DiagnoseResult(surface="langfuse", ok=False, detail="nope"),
    )
    code = diagnose.run()
    assert code == 1
    out = capsys.readouterr().out
    assert "otel" in out
    assert "langfuse" in out
    assert "FAIL" in out


@pytest.mark.unit
def test_run_returns_zero_when_all_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        diagnose,
        "_otel_smoke",
        lambda: diagnose.DiagnoseResult(surface="otel", ok=True, detail="ok"),
    )
    monkeypatch.setattr(
        diagnose,
        "_langfuse_smoke",
        lambda: diagnose.DiagnoseResult(surface="langfuse", ok=True, detail="ok"),
    )
    code = diagnose.run()
    assert code == 0
    out = capsys.readouterr().out
    assert "all 2 surfaces ok" in out
