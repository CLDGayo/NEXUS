"""Unit tests for the FastEmbed pre-flight validator.

Covers the discovery-based ghost-cache sweep, the failing-path parser, and
the main() exit-code contract. No real fastembed downloads happen —
provisioning is monkey-patched.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def validator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import a fresh copy of preflight_validator with CACHE_DIR=tmp_path."""

    monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")

    import preflight_validator

    module = importlib.reload(preflight_validator)
    assert module.CACHE_DIR == tmp_path
    return module


def _make_snapshot(
    cache_root: Path,
    cache_dir_name: str,
    *,
    onnx_size: int | None,
    onnx_filename: str = "model.onnx",
) -> Path:
    """Create an HF-style snapshot dir.

    ``cache_dir_name`` is the actual on-disk dir (e.g. the upstream-resolved
    name ``models--qdrant--bge-small-en-v1.5-onnx-q``), NOT the user-facing
    model id, since FastEmbed remaps ids → repo names internally.
    """

    model_dir = cache_root / cache_dir_name
    snapshot = model_dir / "snapshots" / "deadbeef"
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "config.json").write_text("{}")
    if onnx_size is not None:
        (snapshot / onnx_filename).write_bytes(b"\x00" * onnx_size)
    return model_dir


@pytest.mark.unit
def test_sweep_empty_cache(validator, tmp_path: Path) -> None:
    assert validator._purge_all_ghost_caches() == 0


@pytest.mark.unit
def test_sweep_purges_missing_onnx(validator, tmp_path: Path) -> None:
    # Mimics the real bug: BAAI/bge-small-en-v1.5 maps to a qdrant repo
    # whose snapshot dir exists but lacks model_optimized.onnx.
    ghost = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=None,
    )
    assert validator._purge_all_ghost_caches() == 1
    assert not ghost.exists()


@pytest.mark.unit
def test_sweep_purges_truncated_onnx(validator, tmp_path: Path) -> None:
    ghost = _make_snapshot(
        tmp_path,
        "models--Xenova--ms-marco-MiniLM-L-6-v2",
        onnx_size=1024,
    )
    assert validator._purge_all_ghost_caches() == 1
    assert not ghost.exists()


@pytest.mark.unit
def test_sweep_preserves_healthy(validator, tmp_path: Path) -> None:
    healthy = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=validator.MIN_ONNX_BYTES + 1,
        onnx_filename="model_optimized.onnx",
    )
    assert validator._purge_all_ghost_caches() == 0
    assert healthy.exists()


@pytest.mark.unit
def test_sweep_mixed(validator, tmp_path: Path) -> None:
    healthy = _make_snapshot(
        tmp_path,
        "models--Xenova--ms-marco-MiniLM-L-6-v2",
        onnx_size=validator.MIN_ONNX_BYTES + 1,
    )
    ghost = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=None,
    )
    assert validator._purge_all_ghost_caches() == 1
    assert healthy.exists()
    assert not ghost.exists()


@pytest.mark.unit
def test_ghost_dir_from_exc_parses_path(validator, tmp_path: Path) -> None:
    model_dir = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=None,
    )
    onnx = (
        model_dir / "snapshots" / "deadbeef" / "model_optimized.onnx"
    )
    msg = (
        f"[ONNXRuntimeError] : 3 : NO_SUCHFILE : Load model from {onnx} "
        f"failed:Load model {onnx} failed. File doesn't exist"
    )
    exc = RuntimeError(msg)
    assert validator._ghost_dir_from_exc(exc) == model_dir


@pytest.mark.unit
def test_ghost_dir_from_exc_no_match(validator) -> None:
    assert validator._ghost_dir_from_exc(RuntimeError("network down")) is None


@pytest.mark.unit
def test_provision_with_retry_succeeds_first_call(validator) -> None:
    calls = []

    def _ok() -> None:
        calls.append(1)

    assert validator._provision_with_retry("X", _ok) is True
    assert calls == [1]


@pytest.mark.unit
def test_provision_with_retry_recovers_after_purge(
    validator, tmp_path: Path
) -> None:
    model_dir = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=None,
    )
    onnx = model_dir / "snapshots" / "deadbeef" / "model_optimized.onnx"
    msg = f"Load model from {onnx} failed: missing"

    state = {"calls": 0}

    def _flaky() -> None:
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError(msg)

    assert validator._provision_with_retry("X", _flaky) is True
    assert state["calls"] == 2
    assert not model_dir.exists()


@pytest.mark.unit
def test_provision_with_retry_gives_up_after_second_failure(
    validator, tmp_path: Path
) -> None:
    model_dir = _make_snapshot(
        tmp_path,
        "models--qdrant--bge-small-en-v1.5-onnx-q",
        onnx_size=None,
    )
    onnx = model_dir / "snapshots" / "deadbeef" / "model_optimized.onnx"
    msg = f"Load model from {onnx} failed"

    def _always_fails() -> None:
        raise RuntimeError(msg)

    assert validator._provision_with_retry("X", _always_fails) is False


@pytest.mark.unit
def test_main_happy_path(
    validator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validator, "_provision_embed", lambda: None)
    monkeypatch.setattr(validator, "_provision_rerank", lambda: None)
    assert validator.main() == 0


@pytest.mark.unit
def test_main_exits_nonzero_on_unrecoverable_failure(
    validator, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> None:
        raise RuntimeError("non-onnx network error")

    monkeypatch.setattr(validator, "_provision_embed", _boom)
    monkeypatch.setattr(validator, "_provision_rerank", lambda: None)
    assert validator.main() == 1
