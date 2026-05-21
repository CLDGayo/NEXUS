"""Pre-flight model integrity validator.

Run synchronously before uvicorn. Purges ghost-cache artifacts (partial HF
snapshots with missing or truncated ``*.onnx`` files) and forces a clean
synchronous download of the embed and rerank models. Exits non-zero on
provisioning failure so the container restart loop retries with a clean
volume on the next attempt.

Standalone: no FastAPI, no ``rag.main``, no Pydantic Settings. Reads
configuration directly from environment variables to keep cold-start
overhead negligible on the cache-hit path.

Why the walk is discovery-based instead of model-id-keyed
---------------------------------------------------------
FastEmbed re-routes user-facing model ids to its own canonical HF repos —
e.g. ``BAAI/bge-small-en-v1.5`` resolves to ``qdrant/bge-small-en-v1.5-onnx-q``
on disk. Predicting that mapping from the user-facing id is brittle and
already broke once in production. Walking ``CACHE_DIR/models--*`` and
inspecting every existing snapshot is repo-name-agnostic and catches any
orphan ghost regardless of upstream rename. Additionally, if the
synchronous instantiation itself fails with ``NoSuchFile``, we parse the
failing path out of the exception, purge it, and retry exactly once
before bailing.
"""

from __future__ import annotations

import logging
import os
import re
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


def _purge_all_ghost_caches() -> int:
    """Sweep every ``models--*`` dir under CACHE_DIR; purge incomplete ones.

    Returns the count of directories purged. A directory is considered
    a ghost cache if it contains zero ``*.onnx`` files or if its
    smallest ``*.onnx`` file is below ``MIN_ONNX_BYTES``.
    """

    if not CACHE_DIR.exists():
        log.info("cache dir absent — nothing to sweep")
        return 0

    purged = 0
    for model_dir in sorted(CACHE_DIR.glob("models--*")):
        if not model_dir.is_dir():
            continue
        onnx_files = list(model_dir.rglob("*.onnx"))
        if not onnx_files:
            log.warning("GHOST CACHE: no *.onnx under %s — purging", model_dir)
            shutil.rmtree(model_dir)
            purged += 1
            continue
        smallest = min(onnx_files, key=lambda p: p.stat().st_size)
        size = smallest.stat().st_size
        if size < MIN_ONNX_BYTES:
            log.warning(
                "GHOST CACHE: truncated onnx %s (%d bytes) — purging %s",
                smallest,
                size,
                model_dir,
            )
            shutil.rmtree(model_dir)
            purged += 1
            continue
        log.info(
            "cache OK: %s (%d onnx files, smallest=%d bytes)",
            model_dir.name,
            len(onnx_files),
            size,
        )
    return purged


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


# Matches the path embedded in onnxruntime's NoSuchFile message, e.g.:
#   "Load model from /home/nexus/.cache/fastembed/.../model_optimized.onnx
#    failed: ..."
_NO_SUCHFILE_PATH_RE = re.compile(r"Load model from (\S+\.onnx)")


def _ghost_dir_from_exc(exc: BaseException) -> Path | None:
    """Extract the ``models--*`` ancestor of the missing onnx, if any."""

    match = _NO_SUCHFILE_PATH_RE.search(str(exc))
    if not match:
        return None
    onnx_path = Path(match.group(1))
    for parent in onnx_path.parents:
        if parent.name.startswith("models--") and parent.parent == CACHE_DIR:
            return parent
    return None


def _provision_with_retry(model_id: str, provision: Callable[[], None]) -> bool:
    """Run ``provision``; on NoSuchFile, purge the named dir + retry once."""

    log.info("provisioning %s...", model_id)
    try:
        provision()
        return True
    except Exception as exc:
        ghost = _ghost_dir_from_exc(exc)
        if ghost is None or not ghost.exists():
            log.exception("FATAL: failed to provision %s (no recoverable path)", model_id)
            return False
        log.warning(
            "RUNTIME GHOST: onnx missing under %s — purging and retrying once",
            ghost,
        )
        shutil.rmtree(ghost)

    try:
        provision()
        return True
    except Exception:
        log.exception("FATAL: %s still failed after purge+retry", model_id)
        return False


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

    purged = _purge_all_ghost_caches()
    log.info("ghost-cache sweep complete (purged=%d)", purged)

    targets: tuple[tuple[str, Callable[[], None]], ...] = (
        (EMBED_MODEL, _provision_embed),
        (RERANK_MODEL, _provision_rerank),
    )
    for model_id, provision in targets:
        if not _provision_with_retry(model_id, provision):
            return 1

    log.info("all targets ready — handing off to uvicorn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
