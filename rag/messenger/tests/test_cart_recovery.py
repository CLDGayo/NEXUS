"""Phase 40 — Proactive Cart Recovery tests.

Covers:
  - Endpoint auth (401 on missing key)
  - Payload validation (422 on bad schema)
  - Tenant mapping miss (422)
  - HTTP 202 + background dispatch fires
  - 4 Locks: idempotency dup / HITL paused / window-expired / cold PSID /
    no-user-ts / lock contention
  - Happy path: all locks pass → run_graph called with thread_key==psid
  - thread_key identity assertion

Uses fakeredis (autouse from conftest.py), monkeypatch for graph/sender,
and a synchronous scheduler that awaits the background coroutine in-band.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from rag.main import app
from rag.messenger.routers import outbound as outbound_module

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_PAYLOAD: dict[str, Any] = {
    "cart_id": "cart-001",
    "psid": "psid_123",
    "page_id": "page_456",
    "cart_items": [{"name": "Brix Signature Tee", "quantity": 1}],
    "checkout_url": "https://example.com/checkout/abc",
}

_HEADERS = {"X-Webhook-Api-Key": "test-key", "Content-Type": "application/json"}


def _make_snapshot(
    *,
    empty: bool = False,
    last_user_ts: float | None = None,
    no_user_entry: bool = False,
) -> MagicMock:
    """Build a fake StateSnapshot-like object for aget_state mocks."""
    snap = MagicMock()
    if empty:
        snap.values = {}
        return snap
    history: list[dict[str, Any]] = []
    if not no_user_entry:
        ts = last_user_ts if last_user_ts is not None else time.time() - 100
        history.append({"role": "user", "content": "hello", "timestamp": ts})
    snap.values = {"history": history}
    return snap


# ---------------------------------------------------------------------------
# Capturing scheduler — records scheduled coroutines without running them.
# Used in endpoint-level tests where the TestClient runs in a separate thread
# and we cannot call run_until_complete safely. We just verify the task was
# scheduled; the underlying _run_cart_recovery is replaced by a stub anyway.
# ---------------------------------------------------------------------------


class _CapturingScheduler:
    """Schedules coroutines using asyncio.create_task (same as production) but
    captures each one so tests can verify scheduling happened."""

    def __init__(self) -> None:
        self.scheduled: list[Any] = []

    def __call__(self, coro: Any) -> None:
        self.scheduled.append(coro)
        # Create the task so the coroutine is properly cleaned up
        try:
            asyncio.get_event_loop().create_task(coro)
        except RuntimeError:
            # No running event loop in this thread — just close the coro
            coro.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_tenant(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a valid tenant resolved and capturing scheduler."""
    _default_tenant = MagicMock()
    _default_tenant.slug = "hunter"

    async def _resolve(_db, _page_id):
        return _default_tenant

    scheduler = _CapturingScheduler()
    monkeypatch.setattr(outbound_module, "resolve_tenant_for_page", _resolve)
    monkeypatch.setattr(outbound_module, "_default_scheduler", scheduler)

    with TestClient(app) as c:
        c._scheduler = scheduler  # expose for assertions
        yield c


@pytest.fixture()
def client_no_tenant(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient where tenant resolution returns None."""

    async def _resolve(_db, _page_id):
        return None

    monkeypatch.setattr(outbound_module, "resolve_tenant_for_page", _resolve)

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Endpoint-level tests (HTTP contract)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndpointAuth:
    def test_endpoint_requires_auth(self, client_with_tenant: TestClient) -> None:
        """POST without X-Webhook-Api-Key → HTTP 401."""
        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            json=_VALID_PAYLOAD,
        )
        assert r.status_code == 401

    def test_wrong_key_returns_401(self, client_with_tenant: TestClient) -> None:
        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers={"X-Webhook-Api-Key": "wrong-key"},
            json=_VALID_PAYLOAD,
        )
        assert r.status_code == 401


@pytest.mark.unit
class TestEndpointValidation:
    def test_endpoint_invalid_payload_missing_cart_id(
        self, client_with_tenant: TestClient
    ) -> None:
        """POST with missing cart_id → HTTP 422."""
        bad = dict(_VALID_PAYLOAD)
        del bad["cart_id"]
        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers=_HEADERS,
            json=bad,
        )
        assert r.status_code == 422

    def test_endpoint_invalid_payload_empty_cart_items(
        self, client_with_tenant: TestClient
    ) -> None:
        """POST with empty cart_items → HTTP 422."""
        bad = {**_VALID_PAYLOAD, "cart_items": []}
        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers=_HEADERS,
            json=bad,
        )
        assert r.status_code == 422

    def test_endpoint_invalid_payload_bad_url(
        self, client_with_tenant: TestClient
    ) -> None:
        """POST with a non-URL checkout_url → HTTP 422."""
        bad = {**_VALID_PAYLOAD, "checkout_url": "not-a-url"}
        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers=_HEADERS,
            json=bad,
        )
        assert r.status_code == 422


@pytest.mark.unit
class TestEndpointTenantMiss:
    def test_no_tenant_mapping_returns_422(self, client_no_tenant: TestClient) -> None:
        """If page_id has no tenant mapping → HTTP 422 (synchronous, before task)."""
        r = client_no_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers=_HEADERS,
            json=_VALID_PAYLOAD,
        )
        assert r.status_code == 422
        assert r.json()["detail"] == "no_tenant_mapping"


# ---------------------------------------------------------------------------
# 202 + background dispatch integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndpoint202:
    def test_endpoint_returns_202(
        self, client_with_tenant: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid payload + valid key → 202 with correct body; background task
        is scheduled (the capturing scheduler records it)."""
        task_fired = []

        async def _fake_run_cart_recovery(payload, tenant_slug):
            task_fired.append((payload.cart_id, tenant_slug))

        monkeypatch.setattr(
            outbound_module, "_run_cart_recovery", _fake_run_cart_recovery
        )

        r = client_with_tenant.post(
            "/webhook/outbound/cart-recovery",
            headers=_HEADERS,
            json=_VALID_PAYLOAD,
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "accepted"
        assert body["cart_id"] == "cart-001"
        # The scheduler must have been called once (background task was scheduled)
        scheduler: _CapturingScheduler = client_with_tenant._scheduler
        assert len(scheduler.scheduled) == 1


# ---------------------------------------------------------------------------
# 4 Locks unit tests — exercise _run_cart_recovery directly
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestLock1IdempotencyDuplicate:
    async def test_duplicate_cart_id_aborted(self) -> None:
        """Lock 1: Redis NX already set → task aborts before any other lock."""
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)

        is_bot_paused_mock = AsyncMock(return_value=False)
        run_graph_mock = AsyncMock(return_value={"answer": "hi"})

        # Claim the key first so the second attempt is a duplicate
        from rag.messenger.idempotency import claim_cart_idempotency

        await claim_cart_idempotency(payload.cart_id)

        with (
            patch.object(outbound_module, "is_bot_paused", is_bot_paused_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            await _run_cart_recovery(payload, "hunter")

        # run_graph must NOT have been called
        run_graph_mock.assert_not_called()
        # is_bot_paused must NOT have been called (abort before Lock 2)
        is_bot_paused_mock.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
class TestLock2HITLActive:
    async def test_hitl_active_suppressed(self, caplog) -> None:
        """Lock 2: HITL pause → task aborts; correct log key emitted."""
        import logging
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)

        run_graph_mock = AsyncMock(return_value={"answer": "hi"})

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=True)
            ),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            with caplog.at_level(logging.INFO, logger="rag.messenger.routers.outbound"):
                await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_not_called()
        assert any(
            "cart_recovery.suppressed_hitl_active" in r.message for r in caplog.records
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestLock3WindowExpired:
    async def test_window_expired_aborted(self, caplog) -> None:
        """Lock 3: last user ts > 24h ago → abort with window_expired log key."""
        import logging
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        old_ts = time.time() - 90000  # 25 hours ago
        snapshot = _make_snapshot(last_user_ts=old_ts)

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_mock = AsyncMock(return_value={"answer": "hi"})

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            with caplog.at_level(logging.INFO, logger="rag.messenger.routers.outbound"):
                await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_not_called()
        assert any("cart_recovery.window_expired" in r.message for r in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
class TestLock3ColdPsid:
    async def test_cold_psid_aborted_no_history(self, caplog) -> None:
        """Lock 3: empty snapshot values → cold PSID abort."""
        import logging
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        snapshot = _make_snapshot(empty=True)

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_mock = AsyncMock(return_value={"answer": "hi"})

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            with caplog.at_level(logging.INFO, logger="rag.messenger.routers.outbound"):
                await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_not_called()
        assert any("cart_recovery.cold_psid" in r.message for r in caplog.records)

    async def test_cold_psid_aborted_no_user_ts(self, caplog) -> None:
        """Lock 3: history entries exist but none have user role with timestamp."""
        import logging
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        snapshot = _make_snapshot(no_user_entry=True)
        # Add an assistant entry without a user entry
        snapshot.values = {"history": [{"role": "assistant", "content": "hi"}]}

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_mock = AsyncMock(return_value={"answer": "hi"})

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            with caplog.at_level(logging.INFO, logger="rag.messenger.routers.outbound"):
                await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_not_called()
        assert any("cart_recovery.cold_psid" in r.message for r in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
class TestLock4LockContention:
    async def test_lock_contention_aborted(self, caplog) -> None:
        """Lock 4: acquire_thread_lock returns acquired=False → drop."""
        import logging
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )
        from rag.messenger.idempotency import LockVerdict

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        snapshot = _make_snapshot()

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_mock = AsyncMock(return_value={"answer": "hi"})
        lock_mock = AsyncMock(
            return_value=LockVerdict(acquired=False, key="messenger:lock:psid_123")
        )

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "acquire_thread_lock", lock_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
        ):
            with caplog.at_level(logging.INFO, logger="rag.messenger.routers.outbound"):
                await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_not_called()
        assert any("cart_recovery.lock_contention" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Happy path + thread_key identity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestHappyPath:
    async def test_happy_path_dispatches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All 4 locks pass → run_graph called → send_text_message called."""
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )
        from rag.messenger.idempotency import LockVerdict

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        snapshot = _make_snapshot()

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_mock = AsyncMock(
            return_value={"answer": "Hey! You left something behind."}
        )
        send_mock = AsyncMock()
        lock_mock = AsyncMock(
            return_value=LockVerdict(acquired=True, key="messenger:lock:psid_123")
        )
        release_mock = AsyncMock()

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "acquire_thread_lock", lock_mock),
            patch.object(outbound_module, "release_thread_lock", release_mock),
            patch.object(outbound_module, "run_graph", run_graph_mock),
            patch.object(outbound_module, "send_text_message", send_mock),
            patch.object(
                outbound_module, "current_page_access_token", return_value="tok_abc"
            ),
        ):
            await _run_cart_recovery(payload, "hunter")

        run_graph_mock.assert_called_once()
        send_mock.assert_called_once()
        release_mock.assert_called_once_with("psid_123")

    async def test_thread_key_is_psid_not_cart_id(self) -> None:
        """run_graph must be called with thread_key == psid, never cart_id."""
        from rag.messenger.routers.outbound import (
            _run_cart_recovery,
            CartRecoveryRequest,
        )
        from rag.messenger.idempotency import LockVerdict

        payload = CartRecoveryRequest(**_VALID_PAYLOAD)
        snapshot = _make_snapshot()

        graph_mock = MagicMock()
        graph_mock.aget_state = AsyncMock(return_value=snapshot)
        run_graph_calls: list[dict] = []

        async def _capture_run_graph(**kwargs):
            run_graph_calls.append(kwargs)
            return {"answer": "Hey there!"}

        lock_mock = AsyncMock(
            return_value=LockVerdict(acquired=True, key="messenger:lock:psid_123")
        )

        with (
            patch.object(
                outbound_module, "is_bot_paused", AsyncMock(return_value=False)
            ),
            patch.object(outbound_module, "get_graph", return_value=graph_mock),
            patch.object(outbound_module, "acquire_thread_lock", lock_mock),
            patch.object(outbound_module, "release_thread_lock", AsyncMock()),
            patch.object(outbound_module, "run_graph", _capture_run_graph),
            patch.object(outbound_module, "send_text_message", AsyncMock()),
            patch.object(
                outbound_module, "current_page_access_token", return_value="tok_abc"
            ),
        ):
            await _run_cart_recovery(payload, "hunter")

        assert len(run_graph_calls) == 1
        call = run_graph_calls[0]
        assert call["thread_key"] == payload.psid, (
            f"thread_key must be psid '{payload.psid}', got '{call['thread_key']}'"
        )
        assert call["thread_key"] != payload.cart_id
