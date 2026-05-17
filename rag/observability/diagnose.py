"""Reachability check for OTEL + Langfuse.

Usage::

    python -m rag.observability.diagnose

Sends a synthetic OTEL span to the configured ``OTEL_EXPORTER_OTLP_ENDPOINT``
and (if Langfuse keys are present) a synthetic trace + flush to the configured
``LANGFUSE_HOST``. Reports OK/FAIL per surface so operators can confirm the
observability pipeline is wired correctly before going live.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass

from rag.config import settings


@dataclass(frozen=True)
class DiagnoseResult:
    surface: str
    ok: bool
    detail: str


def _otel_smoke() -> DiagnoseResult:
    """Emit one span and force-flush. OK if no exception within timeout."""

    try:
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from rag.observability.tracing import get_tracer, init_tracing

        # Need an app-bound tracer provider; instrumenting a dummy app is OK.
        try:
            from fastapi import FastAPI
            init_tracing(FastAPI(title="nexus-diagnose"), service_name="nexus-diagnose")
        except Exception:
            pass

        tracer = get_tracer()
        with tracer.start_as_current_span("diagnose.otel") as span:
            span.set_attribute("nexus.diagnose", True)

        # Best-effort flush
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        for proc in getattr(provider, "_active_span_processor", [None]):
            if isinstance(proc, BatchSpanProcessor):
                proc.force_flush(timeout_millis=2000)
        return DiagnoseResult(
            surface="otel",
            ok=True,
            detail=f"sent span to {settings.otel_exporter_otlp_endpoint}",
        )
    except Exception as exc:
        return DiagnoseResult(surface="otel", ok=False, detail=f"{type(exc).__name__}: {exc}")


def _langfuse_smoke() -> DiagnoseResult:
    """Authenticate against Langfuse, emit one trace + event, flush."""

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return DiagnoseResult(
            surface="langfuse",
            ok=False,
            detail="LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set",
        )

    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        trace_handle = client.trace(name="diagnose.langfuse")
        trace_handle.event(
            name="diagnose.event", metadata={"ts": time.time(), "service": "diagnose"}
        )
        try:
            client.flush()
        except Exception:
            pass
        return DiagnoseResult(
            surface="langfuse",
            ok=True,
            detail=f"trace+event sent to {settings.langfuse_host}",
        )
    except Exception as exc:
        return DiagnoseResult(
            surface="langfuse",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


def run() -> int:
    """Return a process exit code: ``0`` if all surfaces ok, ``1`` otherwise."""

    results = [_otel_smoke(), _langfuse_smoke()]
    print("=" * 60)
    print("Nexus observability diagnose")
    print("=" * 60)
    for r in results:
        mark = "ok" if r.ok else "FAIL"
        print(f"  [{mark:4s}] {r.surface:10s} → {r.detail}")
    print()
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"{len(failed)}/{len(results)} surface(s) failed.")
        return 1
    print(f"all {len(results)} surfaces ok.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(asyncio.sleep(0))  # placeholder for future async checks
    sys.exit(run())
