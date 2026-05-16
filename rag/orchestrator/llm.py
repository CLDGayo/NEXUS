"""Thin async client for the LiteLLM proxy.

The orchestrator never talks to provider SDKs directly — every model call
flows through the proxy so routing, rate-limiting, semantic cache, and
Langfuse callbacks are owned in one place. Provider swaps become a config
change in ``litellm/config.yaml`` with no code edits.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rag.config import settings

_log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the proxy returns a non-2xx response or times out."""


async def chat_complete(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout_seconds: float = 30.0,
    extra: dict[str, Any] | None = None,
) -> str:
    """POST ``/chat/completions`` and return the assistant content string."""

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
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected litellm response shape: {body!r}") from exc
