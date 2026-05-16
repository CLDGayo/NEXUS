"""Tracing decorators shared by Phase 2+ surface adapters.

Wraps an async function in an OTEL span + optional Langfuse observation.
Used by every webhook handler so latency, success/error rates, and
correlation IDs are visible in both backends before LangGraph nodes land.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from rag.observability.tracing import get_langfuse, get_tracer

P = ParamSpec("P")
R = TypeVar("R")


def traced(
    name: str, *, kind: str = "span"
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async handler with OTEL + Langfuse tracing.

    Args:
        name: Span / observation name. Use dot-namespaced strings, e.g.
            ``"webhook.messenger.inbound"``.
        kind: Free-form tag (``webhook``, ``llm``, ``retrieval`` …) stored as
            the ``nexus.kind`` span attribute.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = get_tracer()
            langfuse = get_langfuse()
            started_at = time.perf_counter()

            with tracer.start_as_current_span(name) as span:
                span.set_attribute("nexus.kind", kind)

                lf_trace = None
                if langfuse is not None:
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

        return wrapper

    return decorator
