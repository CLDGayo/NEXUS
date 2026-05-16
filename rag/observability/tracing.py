"""OpenTelemetry + Langfuse bootstrap for Nexus v2.

Phase 2 uses this to instrument FastAPI HTTP requests (auto, via
``FastAPIInstrumentor``) and to back the ``@traced`` decorator that webhook
handlers wrap themselves with. Phase 9 will extend with LangGraph node spans
and LiteLLM call tracing.

The Langfuse client is only constructed when both public+secret keys are
present in the environment — keeps local dev and unit tests free of
network dependencies.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI
from langfuse import Langfuse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from rag.config import settings

_log = logging.getLogger(__name__)

_langfuse: Optional[Langfuse] = None
_tracer: Optional[trace.Tracer] = None
_initialized: bool = False


def init_tracing(app: FastAPI, service_name: str = "nexus-messenger") -> None:
    """Bootstrap OTEL TracerProvider, OTLP gRPC exporter, and Langfuse.

    Idempotent — safe to call multiple times. Instruments the supplied
    FastAPI app so request spans propagate automatically.
    """

    global _langfuse, _tracer, _initialized

    if not _initialized:
        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: service_name})
        )
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint, insecure=True
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        _initialized = True
        _log.info(
            "otel tracer initialized",
            extra={"endpoint": settings.otel_exporter_otlp_endpoint, "service": service_name},
        )

    if (
        _langfuse is None
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _log.info("langfuse client initialized", extra={"host": settings.langfuse_host})

    # FastAPIInstrumentor is itself idempotent on a per-app basis.
    FastAPIInstrumentor.instrument_app(app)


def get_tracer() -> trace.Tracer:
    """Return the configured tracer, falling back to the global default."""

    if _tracer is None:
        return trace.get_tracer("nexus-messenger")
    return _tracer


def get_langfuse() -> Optional[Langfuse]:
    """Return the Langfuse client if configured, else ``None``.

    Callers should treat ``None`` as "no-op" rather than as an error so the
    surface keeps working when observability is disabled (tests, smoke runs).
    """

    return _langfuse
