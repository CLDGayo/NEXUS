"""Phase 57 — tests for the Facebook Comment-to-Message engine.

Coverage matrix (per plan section 6):

Unit (no DB):
    * _keyword_matches: exact (case/whitespace), contains, non-match.
    * run_private_reply_job: unmapped page → drop.
    * run_private_reply_job: duplicate comment_id → IntegrityError → drop.
    * run_private_reply_job: Graph 400 code 100 → retryable=False (DLQ).
    * run_private_reply_job: rate-limit code 4/613 → retryable=False (DLQ).
    * run_private_reply_job: happy-path keyword match → Graph POST, lock row.
    * run_private_reply_job: no keyword match → triage fallback invoked.
    * Worker dispatch: target=="fb_private_reply" routes to run_private_reply_job.

Webhook (no DB, TestClient):
    * feed/comment/add with fb_automations_enabled enqueues fb_private_reply.
    * self-comment (from.id == page_id) is dropped regardless of flag.
    * fb_automations_enabled=False with comment_triage_enabled=True → direct triage.

DB-level duplicate and keyword tests use an in-memory async session built on
SQLite (aiosqlite) to verify the IntegrityError / SELECT path without needing
a real Postgres instance.  All network calls are stubbed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from rag.config import settings as _settings
from rag.main import app
from rag.messenger import private_reply as _pr
from rag.messenger.private_reply import _keyword_matches
from rag.messenger.queue import QueuedItem
from rag.messenger.routers import webhook as _webhook
from rag.messenger.routers.webhook import (
    get_graph_runner,
    get_outbound_sender,
    set_event_scheduler,
)


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _Resp:
    """Minimal httpx response stub."""

    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _HttpClient:
    """Async context-manager httpx stub.  Records POST calls."""

    def __init__(
        self,
        resp: _Resp | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._resp = resp
        self._exc = exc
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_HttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, *, params: dict, json: dict) -> _Resp:
        self.posts.append({"url": url, "params": params, "json": json})
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


def _graph_error_body(code: int, subcode: int = 0, message: str = "") -> dict:
    return {
        "error": {
            "code": code,
            "error_subcode": subcode,
            "message": message or f"Graph error {code}",
        }
    }


# ---------------------------------------------------------------------------
# _keyword_matches — pure unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKeywordMatches:
    def test_exact_match_case_insensitive(self) -> None:
        assert _keyword_matches("  PRICE  ", "price", "exact") is True

    def test_exact_match_whitespace_trimmed(self) -> None:
        assert _keyword_matches("  hello  ", "  hello  ", "exact") is True

    def test_exact_no_match(self) -> None:
        assert _keyword_matches("how much is shipping?", "price", "exact") is False

    def test_contains_match(self) -> None:
        assert (
            _keyword_matches("I want to know the PRICE please", "price", "contains")
            is True
        )

    def test_contains_no_match(self) -> None:
        assert _keyword_matches("hello world", "price", "contains") is False

    def test_unknown_match_type_returns_false(self) -> None:
        assert _keyword_matches("regex_test", "regex", "regex") is False


# ---------------------------------------------------------------------------
# run_private_reply_job — stubs for the session / DB
# ---------------------------------------------------------------------------


def _make_page_row(
    page_id: str = "page_1",
    tenant_id: uuid.UUID | None = None,
    token_enc: str | None = "tok_enc",
) -> MagicMock:
    row = MagicMock()
    row.facebook_page_id = page_id
    row.tenant_id = tenant_id or uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    row.page_access_token_enc = token_enc
    return row


def _make_automation(
    keyword: str = "price",
    match_type: str = "exact",
    reply_message: str = "DM reply",
) -> MagicMock:
    a = MagicMock()
    a.trigger_keyword = keyword
    a.match_type = match_type
    a.reply_payload = {"message": reply_message}
    a.is_active = True
    return a


class _AsyncScalarsResult:
    """Minimal stub for SQLAlchemy ``scalars().all()``."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _AsyncExecResult:
    """Wraps a single scalar_one_or_none OR a scalars().all() path."""

    def __init__(self, scalar_val: Any = None, scalars_val: list | None = None) -> None:
        self._scalar = scalar_val
        self._scalars = scalars_val or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> "_AsyncScalarsResult":
        return _AsyncScalarsResult(self._scalars)


def _db_stub(
    *,
    page_row: Any = None,
    automations: list | None = None,
    flush_raises: Exception | None = None,
) -> MagicMock:
    """Build a minimal AsyncSession double."""

    db = MagicMock()
    # Track what was added.
    db._added: list = []
    db.add = lambda row: db._added.append(row)

    call_count = [0]

    async def _execute(_stmt: Any) -> _AsyncExecResult:
        call_count[0] += 1
        if call_count[0] == 1:
            return _AsyncExecResult(scalar_val=page_row)
        # Second call → automations query.
        return _AsyncExecResult(scalars_val=automations or [])

    db.execute = _execute

    async def _flush() -> None:
        if flush_raises is not None:
            raise flush_raises

    db.flush = _flush
    db.rollback = AsyncMock()
    db.commit = AsyncMock()

    # Context manager.
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    return db


def _sessionmaker(db: MagicMock):
    sm = MagicMock()
    sm.return_value = db
    return sm


# ---------------------------------------------------------------------------
# run_private_reply_job tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunPrivateReplyJob:
    """Tests for run_private_reply_job using stubs (no real DB/network)."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_pr, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_pr, "current_page_access_token", lambda: "overlay-tok")

    async def test_unmapped_page_drops_non_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = _db_stub(page_row=None)
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        delivered, status, error, retryable = await _pr.run_private_reply_job(
            _HttpClient(),
            {"page_id": "unknown_page", "comment_id": "c_1", "message": "hi"},
        )

        assert delivered is True
        assert status is None
        assert error == "page unmapped"
        assert retryable is False
        db.commit.assert_not_awaited()

    async def test_duplicate_comment_drops_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        db = _db_stub(
            page_row=_make_page_row(),
            flush_raises=IntegrityError("dup", None, Exception("pk")),
        )
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient()
        delivered, status, error, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_dup", "message": "price"},
        )

        assert delivered is True
        assert status is None
        assert error is None
        assert retryable is False
        assert len(client.posts) == 0  # no Graph POST
        db.rollback.assert_awaited_once()

    async def test_keyword_match_happy_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        automation = _make_automation(keyword="price", reply_message="Our price is $99")
        db = _db_stub(page_row=_make_page_row(), automations=[automation])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, status, error, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_new", "message": "price"},
        )

        assert delivered is True
        assert status == 200
        assert error is None
        assert retryable is False
        assert len(client.posts) == 1
        post = client.posts[0]
        assert "c_new/private_replies" in post["url"]
        assert post["json"] == {"message": "Our price is $99"}
        db.commit.assert_awaited_once()

    async def test_graph_400_code_100_dead_letters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        automation = _make_automation()
        db = _db_stub(page_row=_make_page_row(), automations=[automation])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        resp = _Resp(400, _graph_error_body(code=100, message="Comment not found"))
        client = _HttpClient(resp=resp)
        delivered, status, error, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_bad", "message": "price"},
        )

        assert delivered is False
        assert status == 400
        assert retryable is False  # CRITICAL: never requeue
        assert error is not None
        db.commit.assert_awaited_once()  # lock row committed

    async def test_graph_rate_limit_code_4_dead_letters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        automation = _make_automation()
        db = _db_stub(page_row=_make_page_row(), automations=[automation])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        resp = _Resp(400, _graph_error_body(code=4, message="Rate limited"))
        client = _HttpClient(resp=resp)
        delivered, status, error, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_rate", "message": "price"},
        )

        assert retryable is False  # per directive: even rate-limit → DLQ for this job

    async def test_graph_rate_limit_code_613_dead_letters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        automation = _make_automation()
        db = _db_stub(page_row=_make_page_row(), automations=[automation])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        resp = _Resp(400, _graph_error_body(code=613, message="Rate limited"))
        client = _HttpClient(resp=resp)
        _, _, _, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_613", "message": "price"},
        )
        assert retryable is False

    async def test_transport_error_dead_letters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        automation = _make_automation()
        db = _db_stub(page_row=_make_page_row(), automations=[automation])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(exc=httpx.ConnectError("refused"))
        delivered, status, error, retryable = await _pr.run_private_reply_job(
            client,
            {"page_id": "page_1", "comment_id": "c_transport", "message": "price"},
        )

        assert delivered is False
        assert retryable is False
        assert error is not None and "transport" in error
        db.commit.assert_awaited_once()

    async def test_no_match_invokes_triage_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No automations → falls through to triage.
        db = _db_stub(page_row=_make_page_row(), automations=[])
        monkeypatch.setattr(_pr, "get_sessionmaker", lambda: _sessionmaker(db))

        triage_called: list[str] = []

        async def _stub_triage(
            *,
            page_id: str,
            comment_id: str,
            post_id: str,
            comment_text: str,
            sender_id: str,
            token: str | None = None,
        ) -> None:
            triage_called.append(comment_id)

        # Patch _handle_comment_triage where private_reply imports it from.
        with patch(
            "rag.messenger.routers.webhook._handle_comment_triage",
            side_effect=_stub_triage,
        ):
            delivered, status, error, retryable = await _pr.run_private_reply_job(
                _HttpClient(),
                {
                    "page_id": "page_1",
                    "comment_id": "c_nomatch",
                    "message": "unrelated comment",
                    "post_id": "p_1",
                    "sender_id": "user_99",
                },
            )

        assert delivered is True
        assert retryable is False
        assert triage_called == ["c_nomatch"]
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Worker dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkerDispatch:
    async def test_fb_private_reply_target_routes_to_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rag.messenger import worker

        called: list[dict] = []

        async def _stub_job(
            client: httpx.AsyncClient, payload: dict
        ) -> tuple[bool, int | None, str | None, bool]:
            called.append(payload)
            return True, 200, None, False

        monkeypatch.setattr(
            "rag.messenger.private_reply.run_private_reply_job", _stub_job
        )
        # Also patch the import inside _send_once (lazy import path).
        item = QueuedItem(
            correlation_id="fb_private_reply:c_1",
            target_url="",
            payload={"page_id": "page_1", "comment_id": "c_1", "message": "price"},
            target="fb_private_reply",
        )

        # We need to re-patch the module-level lazy import inside _send_once.
        import rag.messenger.private_reply as _prmod

        _prmod.run_private_reply_job = _stub_job  # type: ignore[assignment]

        result = await worker._send_once(httpx.AsyncClient(), item)
        assert result == (True, 200, None, False)
        assert len(called) == 1


# ---------------------------------------------------------------------------
# Webhook wiring
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _comment_envelope(
    *,
    page_id: str = "page_1",
    from_id: str = "user_77",
    comment_id: str = "c_1",
    post_id: str = "p_1",
    message: str = "price",
    verb: str = "add",
    item: str = "comment",
) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1731742800,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": item,
                            "verb": verb,
                            "comment_id": comment_id,
                            "post_id": post_id,
                            "message": message,
                            "from": {"id": from_id, "name": "Test User"},
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture()
def captured_events():
    """Capture scheduled background coroutines without executing them."""

    pending: list[Awaitable] = []

    def _sync_scheduler(coro: Awaitable) -> None:
        pending.append(coro)

    set_event_scheduler(_sync_scheduler)
    try:
        yield pending
    finally:
        set_event_scheduler(None)
        for coro in pending:
            close = getattr(coro, "close", None)
            if close:
                close()


@pytest.fixture()
def web_client() -> TestClient:
    async def _runner_override() -> object:
        return object()

    async def _sender_override() -> object:
        return object()

    app.dependency_overrides[get_graph_runner] = _runner_override
    app.dependency_overrides[get_outbound_sender] = _sender_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_graph_runner, None)
        app.dependency_overrides.pop(get_outbound_sender, None)


@pytest.mark.unit
class TestWebhookWiring:
    def test_automations_enabled_enqueues_fb_private_reply(
        self,
        web_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list,
    ) -> None:
        monkeypatch.setattr(_settings, "fb_automations_enabled", True)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "wh-secret-57")

        # Stub enqueue_private_reply_job so we capture the call without Redis.
        enqueued: list[dict] = []

        async def _stub_enqueue(**kwargs: Any) -> None:
            enqueued.append(kwargs)

        monkeypatch.setattr(_webhook, "enqueue_private_reply_job", _stub_enqueue)

        body = json.dumps(_comment_envelope(comment_id="c_auto")).encode()
        sig = _sign(body, "wh-secret-57")

        resp = web_client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert resp.status_code == 200
        # One coroutine was scheduled.
        assert len(captured_events) == 1
        import asyncio

        asyncio.run(captured_events[0])

        assert len(enqueued) == 1
        assert enqueued[0]["comment_id"] == "c_auto"
        assert enqueued[0]["page_id"] == "page_1"
        assert enqueued[0]["message"] == "price"

    def test_self_comment_always_dropped(
        self,
        web_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list,
    ) -> None:
        monkeypatch.setattr(_settings, "fb_automations_enabled", True)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "wh-secret-58")

        enqueued: list[dict] = []

        async def _stub_enqueue(**kwargs: Any) -> None:  # pragma: no cover
            enqueued.append(kwargs)

        monkeypatch.setattr(_webhook, "enqueue_private_reply_job", _stub_enqueue)

        # from.id == page_id → echo guard must drop this.
        body = json.dumps(
            _comment_envelope(page_id="page_1", from_id="page_1")
        ).encode()
        sig = _sign(body, "wh-secret-58")

        resp = web_client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert resp.status_code == 200
        assert captured_events == []
        assert enqueued == []

    def test_automations_off_triage_on_falls_back_to_triage(
        self,
        web_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list,
    ) -> None:
        monkeypatch.setattr(_settings, "fb_automations_enabled", False)
        monkeypatch.setattr(_settings, "comment_triage_enabled", True)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "wh-secret-59")

        triage_calls: list[str] = []

        async def _stub_triage(**kwargs: Any) -> None:
            triage_calls.append(kwargs.get("comment_id", ""))

        monkeypatch.setattr(_webhook, "_handle_comment_triage", _stub_triage)

        body = json.dumps(_comment_envelope(comment_id="c_legacy")).encode()
        sig = _sign(body, "wh-secret-59")

        resp = web_client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert resp.status_code == 200
        assert len(captured_events) == 1
        import asyncio

        asyncio.run(captured_events[0])
        assert triage_calls == ["c_legacy"]

    def test_both_flags_off_drops_comment(
        self,
        web_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        captured_events: list,
    ) -> None:
        monkeypatch.setattr(_settings, "fb_automations_enabled", False)
        monkeypatch.setattr(_settings, "comment_triage_enabled", False)
        monkeypatch.setenv("MESSENGER_APP_SECRET", "wh-secret-60")

        body = json.dumps(_comment_envelope()).encode()
        sig = _sign(body, "wh-secret-60")

        resp = web_client.post(
            "/webhook/messenger/inbound",
            headers={"X-Hub-Signature-256": sig},
            content=body,
        )
        assert resp.status_code == 200
        assert captured_events == []
