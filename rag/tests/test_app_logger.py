"""Phase 25.1 — root logger routing tests.

Guards the fix for the silent ``intent=`` log dropout. Pre-fix,
``logging.getLogger("rag.orchestrator.nodes").info(...)`` propagated to
the root logger which had no handlers and a WARNING level filter; the
record was discarded both from ``data/app.log`` and from stdout. After
the fix, ``setup_logger`` attaches FileHandler + StreamHandler +
RingHandler to the root logger so any ``logging.getLogger(__name__)``
child logger lands in both sinks.
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pytest


def _reset_root_logger() -> tuple[list[logging.Handler], int]:
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for h in saved:
        root.removeHandler(h)
    nexus = logging.getLogger("nexus")
    for h in list(nexus.handlers):
        nexus.removeHandler(h)
    return saved, saved_level


def _restore_root_logger(
    saved: list[logging.Handler], saved_level: int
) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


def _patch_log_path(new_path: Path) -> str:
    """Patch ``LOG_PATH`` on every loaded copy of ``app_logger`` and
    return the original value so the caller can restore it."""

    original: str | None = None
    for mod_name in ("app_logger", "rag.app_logger"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            if original is None:
                original = mod.LOG_PATH
            mod.LOG_PATH = str(new_path)
    assert original is not None, "app_logger was not imported"
    return original


def _restore_log_path(value: str) -> None:
    for mod_name in ("app_logger", "rag.app_logger"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            mod.LOG_PATH = value


@pytest.mark.unit
def test_root_logger_picks_up_module_loggers(tmp_path: Path) -> None:
    import app_logger

    tmp_log = tmp_path / "app.log"
    saved, saved_level = _reset_root_logger()
    original_path = _patch_log_path(tmp_log)
    try:
        app_logger.setup_logger()

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if getattr(h, "_nexus", None) == "file"
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == str(tmp_log)

        fake = logging.getLogger("rag.fake.child")
        fake.info("fuse.weighted intent=conceptual weights={'dense': 1.5}")

        for h in root.handlers:
            h.flush()

        assert tmp_log.exists()
        contents = tmp_log.read_text()
        assert "fuse.weighted intent=conceptual" in contents
        assert "rag.fake.child" in contents

        # Stream sink probe.
        probe = io.StringIO()
        probe_handler = logging.StreamHandler(probe)
        probe_handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        root.addHandler(probe_handler)
        try:
            fake.info("fuse.weighted intent=factual")
        finally:
            root.removeHandler(probe_handler)
        assert "fuse.weighted intent=factual" in probe.getvalue()
    finally:
        _restore_log_path(original_path)
        _restore_root_logger(saved, saved_level)


@pytest.mark.unit
def test_setup_logger_is_idempotent(tmp_path: Path) -> None:
    import app_logger

    saved, saved_level = _reset_root_logger()
    original_path = _patch_log_path(tmp_path / "app.log")
    try:
        app_logger.setup_logger()
        first_count = len(logging.getLogger().handlers)

        app_logger.setup_logger()
        second_count = len(logging.getLogger().handlers)

        assert second_count == first_count
    finally:
        _restore_log_path(original_path)
        _restore_root_logger(saved, saved_level)


@pytest.mark.unit
def test_nexus_logger_has_no_own_handlers_after_setup(tmp_path: Path) -> None:
    """The legacy ``nexus`` logger must rely on propagation only, otherwise
    every record would be written twice (once via the nexus FileHandler,
    once via the root FileHandler)."""

    import app_logger

    saved, saved_level = _reset_root_logger()
    original_path = _patch_log_path(tmp_path / "app.log")
    try:
        nexus = app_logger.setup_logger()
        assert nexus.name == "nexus"
        assert nexus.handlers == []
        assert nexus.propagate is True
    finally:
        _restore_log_path(original_path)
        _restore_root_logger(saved, saved_level)


@pytest.mark.unit
def test_legacy_nexus_logger_calls_still_reach_file(tmp_path: Path) -> None:
    """``from app_logger import logger; logger.info(...)`` is in active use
    across v1 modules. Records must still land in ``app.log``."""

    import app_logger

    tmp_log = tmp_path / "app.log"
    saved, saved_level = _reset_root_logger()
    original_path = _patch_log_path(tmp_log)
    try:
        legacy = app_logger.setup_logger()
        legacy.info("legacy nexus logger path")

        for h in logging.getLogger().handlers:
            h.flush()

        assert "legacy nexus logger path" in tmp_log.read_text()
    finally:
        _restore_log_path(original_path)
        _restore_root_logger(saved, saved_level)


@pytest.mark.unit
def test_warning_from_orchestrator_module_visible(tmp_path: Path) -> None:
    """A WARNING emitted from ``rag.orchestrator.nodes`` must reach the
    log file via root propagation."""

    import app_logger

    tmp_log = tmp_path / "app.log"
    saved, saved_level = _reset_root_logger()
    original_path = _patch_log_path(tmp_log)
    try:
        app_logger.setup_logger()

        nodes_log = logging.getLogger("rag.orchestrator.nodes")
        nodes_log.warning("generate.empty_completion model=llama")

        for h in logging.getLogger().handlers:
            h.flush()

        assert "generate.empty_completion" in tmp_log.read_text()
    finally:
        _restore_log_path(original_path)
        _restore_root_logger(saved, saved_level)
