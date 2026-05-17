"""Async client for the LiteLLM proxy with Phase 5 observability hooks.

The orchestrator never talks to provider SDKs directly — every model call
flows through the proxy so routing, rate-limiting, semantic cache, and
Langfuse callbacks are owned in one place. Provider swaps become a config
change in ``litellm/config.yaml`` with no code edits.

Returns a structured ``LLMResult`` carrying the content, model, token
counts, and round-trip latency so downstream code (Langfuse generation
events, state bookkeeping, cost dashboards) has everything it needs in one
return value.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from rag.config import settings
from rag.observability.decorators import current_trace_id_hex
from rag.observability.tracing import get_langfuse

_log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the proxy returns a non-2xx response or times out."""


@dataclass(frozen=True)
class LLMResult:
    """Structured response from the proxy.

    Token counts default to ``0`` when the provider does not report usage;
    callers should not treat absence as an error.
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int


def _extract_usage(body: dict[str, Any]) -> tuple[int, int, int]:
    usage = body.get("usage") or {}
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or (prompt + completion))
    return prompt, completion, total


def _record_langfuse_generation(
    *,
    name: str,
    model: str,
    messages: list[dict[str, str]],
    content: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    latency_ms: int,
) -> None:
    """Emit a Langfuse ``generation`` event stitched to the current OTEL
    trace, if Langfuse is configured. No-ops otherwise.

    Langfuse computes price from its model-pricing DB given the model name
    + usage; we don't need to ship costs.
    """

    langfuse = get_langfuse()
    if langfuse is None:
        return

    trace_id = current_trace_id_hex()
    payload: dict[str, Any] = {
        "name": name,
        "model": model,
        "input": messages,
        "output": content,
        "usage_details": {
            "input": prompt_tokens,
            "output": completion_tokens,
            "total": total_tokens,
        },
        "metadata": {"latency_ms": latency_ms},
    }
    if trace_id is not None:
        payload["trace_id"] = trace_id
    try:
        langfuse.generation(**payload)
    except Exception as exc:  # pragma: no cover - never let observability crash the LLM call
        _log.debug("langfuse generation emit failed: %s", exc)


async def chat_complete(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout_seconds: float = 30.0,
    extra: dict[str, Any] | None = None,
    record_observability: bool = True,
) -> LLMResult:
    """POST ``/chat/completions`` and return a structured result.

    The proxy is expected to be OpenAI-compatible (LiteLLM is). On any
    non-2xx, transport error, or unexpected response shape, raises
    ``LLMError`` with diagnostic context.
    """

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra:
        payload.update(extra)

    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.litellm_base_url.rstrip('/')}/chat/completions"

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise LLMError(f"litellm transport error: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(
            f"litellm returned {response.status_code}: {response.text[:200]}"
        )

    body = response.json()
    try:
        content = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected litellm response shape: {body!r}") from exc

    prompt_tokens, completion_tokens, total_tokens = _extract_usage(body)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if record_observability:
        _record_langfuse_generation(
            name=f"llm.chat_complete.{model}",
            model=model,
            messages=messages,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )

    return LLMResult(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )
