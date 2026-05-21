"""Unit tests for the FastEmbed pre-flight validator.

Covers the ghost-cache detection heuristic and the main() exit-code
contract. No real fastembed downloads happen — provisioning is
monkey-patched.
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
    model_id: str,
    *,
    onnx_size: int | None,
) -> Path:
    """Create an HF-style snapshot dir for ``model_id``.

    If ``onnx_size`` is ``None``, no .onnx file is written (config only —
    the "ghost cache" shape). Otherwise an onnx file of that byte size
    is written under the snapshot directory.
    """

    safe = model_id.replace("/", "--")
    model_dir = cache_root / f"models--{safe}"
    snapshot = model_dir / "snapshots" / "deadbeef"
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "config.json").write_text("{}")
    if onnx_size is not None:
        (snapshot / "model.onnx").write_bytes(b"\x00" * onnx_size)
    return model_dir


@pytest.mark.unit
def test_purge_no_cache_dir(validator, tmp_path: Path) -> None:
    assert validator._purge_if_ghost("BAAI/bge-small-en-v1.5") is False
    assert not (tmp_path / "models--BAAI--bge-small-en-v1.5").exists()


@pytest.mark.unit
def test_purge_no_onnx_found(validator, tmp_path: Path) -> None:
    model_dir = _make_snapshot(
        tmp_path, "BAAI/bge-small-en-v1.5", onnx_size=None
    )
    assert model_dir.exists()
    assert validator._purge_if_ghost("BAAI/bge-small-en-v1.5") is True
    assert not model_dir.exists()


@pytest.mark.unit
def test_purge_truncated_onnx(validator, tmp_path: Path) -> None:
    model_dir = _make_snapshot(
        tmp_path, "BAAI/bge-small-en-v1.5", onnx_size=1024
    )
    assert validator._purge_if_ghost("BAAI/bge-small-en-v1.5") is True
    assert not model_dir.exists()


@pytest.mark.unit
def test_purge_healthy_cache(validator, tmp_path: Path) -> None:
    model_dir = _make_snapshot(
        tmp_path,
        "BAAI/bge-small-en-v1.5",
        onnx_size=validator.MIN_ONNX_BYTES + 1,
    )
    assert validator._purge_if_ghost("BAAI/bge-small-en-v1.5") is False
    assert model_dir.exists()


@pytest.mark.unit
def test_main_happy_path(
    validator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validator, "_provision_embed", lambda: None)
    monkeypatch.setattr(validator, "_provision_rerank", lambda: None)
    assert validator.main() == 0


@pytest.mark.unit
def test_main_exits_nonzero_on_provision_failure(
    validator, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> None:
        raise RuntimeError("simulated ONNX failure")

    monkeypatch.setattr(validator, "_provision_embed", _boom)
    monkeypatch.setattr(validator, "_provision_rerank", lambda: None)
    assert validator.main() == 1
