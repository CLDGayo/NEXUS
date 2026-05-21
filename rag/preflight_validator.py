"""Pre-flight model integrity validator.

Run synchronously before uvicorn. Purges ghost-cache artifacts (partial HF
snapshots with missing or truncated ``*.onnx`` files) and forces a clean
synchronous download of the embed and rerank models. Exits non-zero on
provisioning failure so the container restart loop retries with a clean
volume on the next attempt.

Standalone: no FastAPI, no ``rag.main``, no Pydantic Settings. Reads
configuration directly from environment variables to keep cold-start
overhead negligible on the cache-hit path.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
CACHE_DIR = Path(
    os.environ.get("FASTEMBED_CACHE_DIR", "/home/nexus/.cache/fastembed")
)
# Both target models weigh in well above 20 MiB on disk. A 1 MiB floor
# catches truncated downloads without false-positiving any legitimate
# build of either model.
MIN_ONNX_BYTES = 1_048_576

log = logging.getLogger("preflight")


def _hf_dir_for(model_id: str) -> Path:
    """Resolve the Hugging Face snapshot directory inside the cache."""

    safe = model_id.replace("/", "--")
    return CACHE_DIR / f"models--{safe}"


def _purge_if_ghost(model_id: str) -> bool:
    """Inspect the cache for ``model_id`` and purge it if incomplete.

    Returns ``True`` if a purge was performed, ``False`` if the cache is
    either healthy or absent.
    """

    target_dir = _hf_dir_for(model_id)
    if not target_dir.exists():
        log.info("no cache dir for %s — fresh download required", model_id)
        return False

    onnx_files = list(target_dir.rglob("*.onnx"))
    if not onnx_files:
        log.warning("GHOST CACHE: no *.onnx under %s — purging", target_dir)
        shutil.rmtree(target_dir)
        return True

    smallest = min(onnx_files, key=lambda p: p.stat().st_size)
    size = smallest.stat().st_size
    if size < MIN_ONNX_BYTES:
        log.warning(
            "GHOST CACHE: truncated onnx %s (%d bytes) — purging",
            smallest,
            size,
        )
        shutil.rmtree(target_dir)
        return True

    log.info(
        "cache OK for %s (%d onnx files, smallest=%d bytes)",
        model_id,
        len(onnx_files),
        size,
    )
    return False


def _resolve_cross_encoder_cls():
    """Import ``TextCrossEncoder`` across fastembed versions.

    Mirrors ``rag.retrieval.rerank._load_cross_encoder_cls`` so the two
    code paths cannot drift on the next dependency bump.
    """

    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder
    except ImportError:
        pass
    try:
        from fastembed import TextCrossEncoder  # type: ignore[attr-defined]

        return TextCrossEncoder
    except ImportError as exc:
        raise ImportError(
            "fastembed.TextCrossEncoder unavailable at "
            "`fastembed.rerank.cross_encoder` (>=0.4) or top-level (<0.4). "
            "Pin `fastembed` directly in pyproject.toml."
        ) from exc


def _provision_embed() -> None:
    from fastembed import TextEmbedding

    started = time.monotonic()
    TextEmbedding(model_name=EMBED_MODEL, cache_dir=str(CACHE_DIR))
    log.info("%s ready (%.1fs)", EMBED_MODEL, time.monotonic() - started)


def _provision_rerank() -> None:
    cls = _resolve_cross_encoder_cls()
    started = time.monotonic()
    cls(model_name=RERANK_MODEL, cache_dir=str(CACHE_DIR))
    log.info("%s ready (%.1fs)", RERANK_MODEL, time.monotonic() - started)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s preflight: %(message)s",
    )
    log.info("cache_dir=%s", CACHE_DIR)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("cannot create cache dir %s: %s", CACHE_DIR, exc)
        return 1

    targets: tuple[tuple[str, Callable[[], None]], ...] = (
        (EMBED_MODEL, _provision_embed),
        (RERANK_MODEL, _provision_rerank),
    )
    for model_id, provision in targets:
        log.info("validating %s...", model_id)
        _purge_if_ghost(model_id)
        try:
            provision()
        except Exception:
            log.exception("FATAL: failed to provision %s", model_id)
            return 1

    log.info("all targets ready — handing off to uvicorn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
