"""Phase 5 LLM tracing tests — captures token usage + Langfuse generation
emission with OTEL trace stitching."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from rag.orchestrator import llm as llm_module
from rag.orchestrator.llm import LLMError, LLMResult, chat_complete


def _ok_response(content: str, *, prompt_tokens: int = 12, completion_tokens: int = 4) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "model": "groq-llama-3.3-70b",
    }


class _AsyncClientStub:
    """Substitute for ``httpx.AsyncClient`` in async-context-manager mode."""

    def __init__(self, response_payload: Any | None = None, status_code: int = 200, raise_exc: Exception | None = None) -> None:
        self.payload = response_payload
        self.status_code = status_code
        self.raise_exc = raise_exc
        self.last_post_kwargs: dict | None = None

    async def __aenter__(self) -> "_AsyncClientStub":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url: str, *, headers: dict, json: dict) -> "_Response":
        if self.raise_exc:
            raise self.raise_exc
        self.last_post_kwargs = {"url": url, "headers": headers, "json": json}
        return _Response(self.status_code, self.payload)


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self) -> Any:
        if isinstance(self._payload, dict):
            return self._payload
        raise ValueError("not json")


@pytest.fixture(autouse=True)
def _no_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to no Langfuse so tests don't try real network calls."""

    monkeypatch.setattr(llm_module, "get_langfuse", lambda: None)
    monkeypatch.setattr(llm_module, "current_trace_id_hex", lambda: None)


@pytest.mark.unit
class TestChatComplete:
    async def test_returns_llmresult_with_usage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _AsyncClientStub(response_payload=_ok_response("hello world"))
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)

        result = await chat_complete(
            [{"role": "user", "content": "hi"}], model="groq-llama-3.3-70b"
        )
        assert isinstance(result, LLMResult)
        assert result.content == "hello world"
        assert result.model == "groq-llama-3.3-70b"
        assert result.prompt_tokens == 12
        assert result.completion_tokens == 4
        assert result.total_tokens == 16
        assert result.latency_ms >= 0

    async def test_missing_usage_defaults_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {"choices": [{"message": {"content": "ok"}}]}
        stub = _AsyncClientStub(response_payload=payload)
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)

        result = await chat_complete([{"role": "user", "content": "x"}], model="m")
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0

    async def test_non_2xx_raises_llmerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _AsyncClientStub(response_payload={"error": "bad"}, status_code=503)
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)
        with pytest.raises(LLMError) as exc_info:
            await chat_complete([{"role": "user", "content": "x"}], model="m")
        assert "503" in str(exc_info.value)

    async def test_transport_error_raises_llmerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _AsyncClientStub(
            raise_exc=httpx.ConnectError("connection refused")
        )
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)
        with pytest.raises(LLMError) as exc_info:
            await chat_complete([{"role": "user", "content": "x"}], model="m")
        assert "transport" in str(exc_info.value).lower()

    async def test_unexpected_shape_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No "choices" key
        stub = _AsyncClientStub(response_payload={"foo": "bar"})
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)
        with pytest.raises(LLMError) as exc_info:
            await chat_complete([{"role": "user", "content": "x"}], model="m")
        assert "unexpected" in str(exc_info.value).lower()


@pytest.mark.unit
class TestLangfuseEmission:
    async def test_generation_called_with_usage_and_trace_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _AsyncClientStub(response_payload=_ok_response("ok"))
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)

        fake_langfuse = MagicMock()
        monkeypatch.setattr(llm_module, "get_langfuse", lambda: fake_langfuse)
        monkeypatch.setattr(
            llm_module, "current_trace_id_hex", lambda: "a" * 32
        )

        await chat_complete([{"role": "user", "content": "x"}], model="groq-llama-3.3-70b")
        fake_langfuse.generation.assert_called_once()
        call_kwargs = fake_langfuse.generation.call_args.kwargs
        assert call_kwargs["model"] == "groq-llama-3.3-70b"
        assert call_kwargs["trace_id"] == "a" * 32
        usage = call_kwargs["usage_details"]
        assert usage["input"] == 12
        assert usage["output"] == 4
        assert usage["total"] == 16

    async def test_record_observability_false_skips_emit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _AsyncClientStub(response_payload=_ok_response("ok"))
        monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: stub)

        fake_langfuse = MagicMock()
        monkeypatch.setattr(llm_module, "get_langfuse", lambda: fake_langfuse)

        await chat_complete(
            [{"role": "user", "content": "x"}],
            model="m",
            record_observability=False,
        )
        fake_langfuse.generation.assert_not_called()
