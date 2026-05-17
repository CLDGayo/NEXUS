"""Tracing decorators shared by Phase 2+ surface adapters.

Wraps an async function in an OTEL span. A Langfuse trace is created only
at the outermost call so nested decorated functions emit OTEL spans that
stitch under the same Langfuse trace (via OTEL trace_id propagation through
the otel-collector → Langfuse OTLP receiver pipeline).

Without this root-detection, every decorated call would create its own
Langfuse trace and the UI would explode into N+1 unrelated traces per
request. With it, you get one trace per request and a clean span tree.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from opentelemetry import trace as otel_trace

from rag.observability.tracing import get_langfuse, get_tracer

P = ParamSpec("P")
R = TypeVar("R")


def _is_root_span() -> bool:
    """True when no parent OTEL span is active in this context."""

    current = otel_trace.get_current_span()
    ctx = current.get_span_context()
    # The default ``INVALID`` span has trace_id == 0.
    return ctx.trace_id == 0


def traced(
    name: str, *, kind: str = "span"
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async handler with OTEL + (root-only) Langfuse tracing.

    Args:
        name: Span / observation name. Use dot-namespaced strings, e.g.
            ``"webhook.messenger.inbound"``.
        kind: Free-form tag (``webhook``, ``llm``, ``retrieval`` …) stored
            as the ``nexus.kind`` span attribute and surfaced as the
            Langfuse trace ``metadata.kind``.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = get_tracer()
            langfuse = get_langfuse()
            started_at = time.perf_counter()
            # Capture whether THIS call is the outermost decorated frame.
            is_root = _is_root_span()

            with tracer.start_as_current_span(name) as span:
                span.set_attribute("nexus.kind", kind)

                lf_trace = None
                if langfuse is not None and is_root:
                    lf_trace = langfuse.trace(name=name, metadata={"kind": kind})

                try:
                    result = await fn(*args, **kwargs)
                    span.set_attribute("nexus.outcome", "ok")
                    if lf_trace is not None:
                        lf_trace.update(output={"ok": True})
                    return result
                except Exception as exc:
                    span.set_attribute("nexus.outcome", "error")
                    span.record_exception(exc)
                    if lf_trace is not None:
                        lf_trace.update(level="ERROR", status_message=str(exc))
                    raise
                finally:
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    span.set_attribute("nexus.duration_ms", duration_ms)

        # Preserve the wrapped function's signature so FastAPI keeps the
        # full type annotations of route handlers (Pydantic body schemas,
        # Depends() injections, etc.). `functools.wraps` alone is not
        # enough — FastAPI inspects the signature without following
        # `__wrapped__` in some code paths.
        try:
            wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        except (TypeError, ValueError):  # pragma: no cover - rare
            pass

        return wrapper

    return decorator


def current_trace_id_hex() -> str | None:
    """Return the active OTEL trace id as 32-char hex, or None when no
    span is in scope. Used by the LLM tracing layer to stitch Langfuse
    ``generation`` events to the surrounding trace."""

    current = otel_trace.get_current_span()
    ctx = current.get_span_context()
    if ctx.trace_id == 0:
        return None
    return format(ctx.trace_id, "032x")
