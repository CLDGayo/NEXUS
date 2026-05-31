"""Phase 33 — unit tests for sales SDR tool definitions."""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_CHECKPOINT", "memory")

import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from rag.orchestrator import sales_tools as st


# ---------------------------------------------------------------------------
# Helpers — fake SQLAlchemy session
# ---------------------------------------------------------------------------


@dataclass
class _FakeProduct:
    name: str
    price_cents: int
    currency: str
    quantity: int


class _FakeScalars:
    def __init__(self, rows: list[_FakeProduct]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeProduct]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[_FakeProduct]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def scalars(self, _stmt: Any) -> _FakeScalars:
        return _FakeScalars(self._rows)


def _fake_sessionmaker(rows: list[_FakeProduct]):
    def factory() -> _FakeSession:
        return _FakeSession(rows)

    return lambda: factory()


# ---------------------------------------------------------------------------
# check_inventory
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_check_inventory_formats_matching_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _FakeProduct(
            name="Luffy Gear 4", price_cents=12999, currency="USD", quantity=5
        ),
        _FakeProduct(
            name="Luffy Sun God", price_cents=24999, currency="USD", quantity=0
        ),
    ]
    monkeypatch.setattr(st, "get_sessionmaker", lambda: _fake_sessionmaker(rows))

    result = await st.check_inventory("luffy", tenant_id="acme")

    assert "Luffy Gear 4" in result
    assert "USD 129.99" in result
    assert "5 available" in result
    assert "In stock" in result
    assert "Luffy Sun God" in result
    assert "Out of stock" in result


@pytest.mark.unit
async def test_check_inventory_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(st, "get_sessionmaker", lambda: _fake_sessionmaker([]))

    result = await st.check_inventory("nonexistent", tenant_id="acme")

    assert result == "No products found matching 'nonexistent'."


# ---------------------------------------------------------------------------
# Phase 34 — n8n webhook layer for generate_checkout_link / capture_lead
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for httpx.Response used by the sales tools."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # We never inspect .request inside the sales_tools error handler,
            # so a None placeholder cast is acceptable for the test double.
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("POST", "https://n8n.test/webhook"),
                response=httpx.Response(self.status_code, text=self.text),
            )

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    """Async-context-manager test double for httpx.AsyncClient."""

    def __init__(
        self,
        *,
        response: _FakeResponse | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._response = response
        self._raises = raises
        self.captured_url: str | None = None
        self.captured_json: dict[str, Any] | None = None

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def post(
        self, url: str, *, json: dict[str, Any] | None = None
    ) -> _FakeResponse:
        self.captured_url = url
        self.captured_json = json
        if self._raises is not None:
            raise self._raises
        assert self._response is not None  # configured by the test
        return self._response


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResponse | None = None,
    raises: Exception | None = None,
) -> _FakeAsyncClient:
    """Patch httpx.AsyncClient inside sales_tools and return the live double."""

    fake = _FakeAsyncClient(response=response, raises=raises)
    monkeypatch.setattr(st.httpx, "AsyncClient", lambda **_kw: fake)
    return fake


# ---- generate_checkout_link ----


@pytest.mark.unit
async def test_generate_checkout_link_unconfigured_returns_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(st.settings, "n8n_webhook_checkout_url", None)

    result = await st.generate_checkout_link("Luffy Gear 4", 2)

    assert "Mock link" in result
    assert "N8N_WEBHOOK_CHECKOUT_URL" in result
    assert "Luffy Gear 4" in result
    assert "qty=2" in result


@pytest.mark.unit
async def test_generate_checkout_link_configured_returns_stripe_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        st.settings, "n8n_webhook_checkout_url", "https://n8n.test/webhook/checkout"
    )
    fake = _install_fake_client(
        monkeypatch,
        response=_FakeResponse(
            status=200,
            body={"url": "https://checkout.stripe.com/cs_test_123"},
        ),
    )

    result = await st.generate_checkout_link("Luffy Gear 4", 2)

    assert result == "https://checkout.stripe.com/cs_test_123"
    assert fake.captured_url == "https://n8n.test/webhook/checkout"
    assert fake.captured_json == {"product_name": "Luffy Gear 4", "quantity": 2}


@pytest.mark.unit
async def test_generate_checkout_link_network_timeout_returns_error_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        st.settings, "n8n_webhook_checkout_url", "https://n8n.test/webhook/checkout"
    )
    _install_fake_client(monkeypatch, raises=httpx.TimeoutException("boom"))

    result = await st.generate_checkout_link("Luffy Gear 4", 2)

    assert "Checkout link generation failed" in result
    assert "timed out" in result


# ---- capture_lead ----


@pytest.mark.unit
async def test_capture_lead_unconfigured_returns_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(st.settings, "n8n_webhook_lead_url", None)

    result = await st.capture_lead("buyer@example.com")

    assert "buyer@example.com" in result
    assert "captured successfully" in result
    assert "N8N_WEBHOOK_LEAD_URL" in result


@pytest.mark.unit
async def test_capture_lead_configured_returns_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        st.settings, "n8n_webhook_lead_url", "https://n8n.test/webhook/lead"
    )
    fake = _install_fake_client(
        monkeypatch,
        response=_FakeResponse(status=200, body={"ok": True}),
    )

    result = await st.capture_lead("buyer@example.com")

    assert "buyer@example.com" in result
    assert "captured successfully" in result
    assert "follow up shortly" in result
    assert fake.captured_url == "https://n8n.test/webhook/lead"
    assert fake.captured_json == {"email": "buyer@example.com"}


@pytest.mark.unit
async def test_capture_lead_network_timeout_returns_error_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        st.settings, "n8n_webhook_lead_url", "https://n8n.test/webhook/lead"
    )
    _install_fake_client(monkeypatch, raises=httpx.TimeoutException("boom"))

    result = await st.capture_lead("buyer@example.com")

    assert "Lead capture failed" in result
    assert "buyer@example.com" in result
    assert "timed out" in result


# ---------------------------------------------------------------------------
# execute_tool_call dispatch
# ---------------------------------------------------------------------------


def _tool_call(
    name: str, args: str | dict[str, Any], call_id: str = "tc-1"
) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


@pytest.mark.unit
async def test_execute_tool_call_dispatches_each_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_check(**kwargs: Any) -> str:
        calls.append(("check_inventory", kwargs))
        return "INV"

    async def fake_link(**kwargs: Any) -> str:
        calls.append(("generate_checkout_link", kwargs))
        return "LNK"

    async def fake_lead(**kwargs: Any) -> str:
        calls.append(("capture_lead", kwargs))
        return "LEAD"

    monkeypatch.setitem(st.TOOL_DISPATCH, "check_inventory", fake_check)
    monkeypatch.setitem(st.TOOL_DISPATCH, "generate_checkout_link", fake_link)
    monkeypatch.setitem(st.TOOL_DISPATCH, "capture_lead", fake_lead)

    r1 = await st.execute_tool_call(
        _tool_call("check_inventory", '{"product_name": "X"}', "a"),
        tenant_id="acme",
    )
    r2 = await st.execute_tool_call(
        _tool_call(
            "generate_checkout_link",
            '{"product_name": "X", "quantity": 3}',
            "b",
        ),
        tenant_id="acme",
    )
    r3 = await st.execute_tool_call(
        _tool_call("capture_lead", '{"email": "y@z"}', "c"),
        tenant_id="acme",
    )

    assert r1 == {"role": "tool", "tool_call_id": "a", "content": "INV"}
    assert r2 == {"role": "tool", "tool_call_id": "b", "content": "LNK"}
    assert r3 == {"role": "tool", "tool_call_id": "c", "content": "LEAD"}

    assert calls[0] == ("check_inventory", {"product_name": "X", "tenant_id": "acme"})
    assert calls[1] == (
        "generate_checkout_link",
        {"product_name": "X", "quantity": 3},
    )
    assert calls[2] == ("capture_lead", {"email": "y@z"})


@pytest.mark.unit
async def test_execute_tool_call_unknown_tool() -> None:
    result = await st.execute_tool_call(
        _tool_call("not_a_tool", "{}", "x"),
        tenant_id="acme",
    )
    assert result["content"] == "Unknown tool: not_a_tool"
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "x"


@pytest.mark.unit
async def test_execute_tool_call_bad_json_args_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_check(**kwargs: Any) -> str:
        seen.update(kwargs)
        return "OK"

    monkeypatch.setitem(st.TOOL_DISPATCH, "check_inventory", fake_check)

    result = await st.execute_tool_call(
        _tool_call("check_inventory", "this is not json", "z"),
        tenant_id="acme",
    )

    assert result["content"] == "OK"
    # Bad args fall through to empty defaults — handler still invoked.
    assert seen == {"product_name": "", "tenant_id": "acme"}


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sales_tools_schema_is_openai_compatible() -> None:
    names = {t["function"]["name"] for t in st.SALES_TOOLS_SCHEMA}
    assert names == {
        "check_inventory",
        "generate_checkout_link",
        "capture_lead",
    }

    for entry in st.SALES_TOOLS_SCHEMA:
        assert entry["type"] == "function"
        func = entry["function"]
        assert isinstance(func["name"], str) and func["name"]
        assert isinstance(func["description"], str) and func["description"]
        params = func["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict) and params["properties"]
        assert isinstance(params["required"], list) and params["required"]


@pytest.mark.unit
def test_sdr_persona_overlay_present_and_marked() -> None:
    assert "--- SALES REPRESENTATIVE MODE ---" in st.SDR_PERSONA_OVERLAY
    assert "check_inventory" in st.SDR_PERSONA_OVERLAY
    assert "generate_checkout_link" in st.SDR_PERSONA_OVERLAY
    assert "capture_lead" in st.SDR_PERSONA_OVERLAY
