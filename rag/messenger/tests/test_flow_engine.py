"""Phase 58.1 — unit tests for the NEXUS Flow traversal engine.

Coverage matrix (per plan section 7):

Unit (no DB, no network — all externals stubbed):
    * Trigger keyword match → traversal starts.
    * Condition node picks correct sourceHandle (true/false branch).
    * sendMessage node calls Graph API with facebook_graph_version.
    * waitForInput halts (status='waiting') and stores current_node_id.
    * A following DM (resume_flow_for_dm) resumes from current_node_id.
    * Duplicate comment_id → IntegrityError → silently dropped.
    * Node visit cap exceeded (50+) → cycle guard → run.status='failed'.
    * Graph error on sendMessage → retryable=False (dead-letter).
    * No matching flow → Phase 57 fallback fires (run_private_reply_job called).
    * Worker dispatch: target=="fb_flow" routes to run_flow_job.

All DB interaction is stubbed via the same pattern as test_private_reply.py.
No real Postgres or Redis required.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rag.config import settings as _settings
from rag.messenger import flow_engine as _fe


# ---------------------------------------------------------------------------
# Minimal stubs
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

    async def post(self, url: str, *, params: dict | None = None, json: dict | None = None, **kwargs: Any) -> _Resp:
        self.posts.append({"url": url, "params": params or {}, "json": json or {}})
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


# ---------------------------------------------------------------------------
# DB stub helpers (mirror test_private_reply.py pattern)
# ---------------------------------------------------------------------------


class _AsyncScalarsResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _AsyncExecResult:
    def __init__(self, scalar_val: Any = None, scalars_val: list | None = None) -> None:
        self._scalar = scalar_val
        self._scalars = scalars_val or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> "_AsyncScalarsResult":
        return _AsyncScalarsResult(self._scalars)


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


def _make_flow(
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    is_active: bool = True,
    page_id: str = "page_1",
    tenant_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a minimal NexusFlow stub."""
    flow = MagicMock()
    flow.id = uuid.uuid4()
    flow.page_id = page_id
    flow.is_active = is_active
    flow.tenant_id = tenant_id or uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
    flow.flow_state = {
        "nodes": nodes or [],
        "edges": edges or [],
        "viewport": None,
    }
    return flow


def _comment_trigger_node(
    node_id: str = "n_trigger",
    keyword: str = "price",
    match_type: str = "exact",
) -> dict:
    return {
        "id": node_id,
        "type": "commentTrigger",
        "position": {"x": 0, "y": 0},
        "data": {"keyword": keyword, "matchType": match_type},
    }


def _dm_trigger_node(node_id: str = "n_dm_trigger", keyword: str = "start") -> dict:
    return {
        "id": node_id,
        "type": "dmTrigger",
        "position": {"x": 0, "y": 0},
        "data": {"keyword": keyword, "matchType": "exact"},
    }


def _send_message_node(node_id: str = "n_send", message: str = "Hello!") -> dict:
    return {
        "id": node_id,
        "type": "sendMessage",
        "position": {"x": 200, "y": 0},
        "data": {"message": message},
    }


def _wait_for_input_node(
    node_id: str = "n_wait",
    prompt: str = "What is your email?",
    variable: str = "email",
) -> dict:
    return {
        "id": node_id,
        "type": "waitForInput",
        "position": {"x": 400, "y": 0},
        "data": {"prompt": prompt, "variable": variable},
    }


def _condition_node(
    node_id: str = "n_cond",
    variable: str = "score",
    operator: str = "eq",
    value: Any = "high",
) -> dict:
    return {
        "id": node_id,
        "type": "condition",
        "position": {"x": 200, "y": 0},
        "data": {"variable": variable, "operator": operator, "value": value},
    }


def _edge(src: str, tgt: str, handle: str | None = None) -> dict:
    return {
        "id": f"e_{src}_{tgt}",
        "source": src,
        "target": tgt,
        "sourceHandle": handle,
        "targetHandle": None,
    }


def _db_stub(
    *,
    page_row: Any = None,
    flows: list | None = None,
    flush_raises: Exception | None = None,
    run_row: Any = None,
    flow_row: Any = None,
    tenant_language: str = "en",
) -> MagicMock:
    """Build a minimal AsyncSession double for flow_engine tests."""
    db = MagicMock()
    db._added: list = []

    def _add(row: Any) -> None:
        db._added.append(row)

    db.add = _add

    # Phase 59 — flow_engine loads Tenant.preferred_language via db.scalar.
    db.scalar = AsyncMock(return_value=tenant_language)

    call_count = [0]

    async def _execute(_stmt: Any) -> _AsyncExecResult:
        call_count[0] += 1
        n = call_count[0]
        if n == 1:
            # 1st call: page tenant row
            return _AsyncExecResult(scalar_val=page_row)
        if n == 2:
            # 2nd call: nexus_flows query
            return _AsyncExecResult(scalars_val=flows or [])
        # resume_flow_for_dm calls: run row then flow row
        if n == 1:
            return _AsyncExecResult(scalar_val=run_row)
        if n == 2:
            return _AsyncExecResult(scalar_val=flow_row)
        return _AsyncExecResult()

    db.execute = _execute

    async def _flush() -> None:
        if flush_raises is not None:
            raise flush_raises

    db.flush = _flush
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    return db


def _db_stub_resume(
    *,
    run_row: Any = None,
    flow_row: Any = None,
    tenant_language: str = "en",
) -> MagicMock:
    """DB stub specifically for resume_flow_for_dm (2 select calls)."""
    db = MagicMock()
    db._added: list = []
    db.add = lambda row: db._added.append(row)

    # Phase 59 — resume path loads Tenant.preferred_language via db.scalar.
    db.scalar = AsyncMock(return_value=tenant_language)

    call_count = [0]

    async def _execute(_stmt: Any) -> _AsyncExecResult:
        call_count[0] += 1
        if call_count[0] == 1:
            return _AsyncExecResult(scalar_val=run_row)
        return _AsyncExecResult(scalar_val=flow_row)

    db.execute = _execute
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    return db


def _sessionmaker(db: MagicMock):
    sm = MagicMock()
    sm.return_value = db
    return sm


# ---------------------------------------------------------------------------
# run_flow_job tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunFlowJob:
    """Tests for run_flow_job using stubs (no real DB/network)."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    async def test_unmapped_page_drops_non_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = _db_stub(page_row=None)
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        delivered, status, error, retryable = await _fe.run_flow_job(
            _HttpClient(),
            {"page_id": "unknown_page", "comment_id": "c_1", "message": "price", "sender_id": "u_1"},
        )

        assert delivered is True
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
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient()
        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_dup", "message": "price", "sender_id": "u_1"},
        )

        assert delivered is True
        assert status is None
        assert error is None
        assert retryable is False
        assert len(client.posts) == 0  # no Graph POST
        db.rollback.assert_awaited_once()

    async def test_no_flow_match_falls_back_to_phase57(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No matching active flow → run_private_reply_job called."""
        # Flow exists but keyword doesn't match
        flow = _make_flow(
            nodes=[_comment_trigger_node(keyword="price")],
            edges=[],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        fallback_called: list[dict] = []

        async def _stub_phase57(client: Any, payload: dict) -> tuple:
            fallback_called.append(payload)
            return True, None, None, False

        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        with patch("rag.messenger.flow_engine.run_flow_job") as _:
            # Patch the import inside run_flow_job's fallback path
            with patch(
                "rag.messenger.private_reply.run_private_reply_job",
                side_effect=_stub_phase57,
            ):
                # Direct test: no flows → fallback
                db2 = _db_stub(page_row=_make_page_row(), flows=[])
                monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db2))

                with patch(
                    "rag.messenger.flow_engine.run_flow_job",
                ) as _outer:
                    # Test the logic inside run_flow_job by calling the real function
                    pass

        # Re-do without nested patching confusion:
        fallback_called2: list[dict] = []

        async def _stub_fallback(client: Any, payload: dict) -> tuple:
            fallback_called2.append(payload)
            return True, None, None, False

        db3 = _db_stub(page_row=_make_page_row(), flows=[])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db3))

        import rag.messenger.private_reply as _pr_mod
        original = getattr(_pr_mod, "run_private_reply_job", None)
        _pr_mod.run_private_reply_job = _stub_fallback  # type: ignore[assignment]
        try:
            delivered, status, error, retryable = await _fe.run_flow_job(
                _HttpClient(),
                {
                    "page_id": "page_1",
                    "comment_id": "c_nomatch",
                    "message": "unrelated",
                    "sender_id": "u_1",
                    "post_id": "p_1",
                },
            )
        finally:
            if original is not None:
                _pr_mod.run_private_reply_job = original  # type: ignore[assignment]

        assert len(fallback_called2) == 1
        assert delivered is True
        assert retryable is False

    async def test_trigger_match_starts_traversal_send_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Comment matching trigger keyword → sendMessage node sends Graph POST."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        send = _send_message_node(node_id="n_send", message="Our price is $99")
        flow = _make_flow(
            nodes=[trigger, send],
            edges=[_edge("n_trigger", "n_send")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_new", "message": "price", "sender_id": "u_1"},
        )

        assert delivered is True
        assert error is None
        assert retryable is False
        # One POST to the Graph API (sendMessage node)
        assert len(client.posts) == 1
        post = client.posts[0]
        assert f"/{_settings.facebook_graph_version}/me/messages" in post["url"]
        assert post["json"]["message"]["text"] == "Our price is $99"
        db.commit.assert_awaited()

    async def test_send_message_uses_facebook_graph_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Graph API URL must use settings.facebook_graph_version."""
        monkeypatch.setattr(_settings, "facebook_graph_version", "v21.0")

        trigger = _comment_trigger_node()
        send = _send_message_node()
        flow = _make_flow(
            nodes=[trigger, send],
            edges=[_edge("n_trigger", "n_send")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))
        await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ver", "message": "price", "sender_id": "u_1"},
        )

        assert len(client.posts) == 1
        assert "v21.0" in client.posts[0]["url"]

    async def test_graph_error_dead_letters_retryable_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any Graph error → retryable=False (never requeue)."""
        trigger = _comment_trigger_node()
        send = _send_message_node()
        flow = _make_flow(
            nodes=[trigger, send],
            edges=[_edge("n_trigger", "n_send")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(
            resp=_Resp(400, {"error": {"code": 100, "message": "bad"}}),
        )
        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_err", "message": "price", "sender_id": "u_1"},
        )

        assert delivered is False
        assert retryable is False  # CRITICAL
        assert error is not None

    async def test_wait_for_input_halts_with_waiting_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """waitForInput node → run.status='waiting', current_node_id set, traversal halts."""
        trigger = _comment_trigger_node()
        wait = _wait_for_input_node(node_id="n_wait", prompt="Email?")
        flow = _make_flow(
            nodes=[trigger, wait],
            edges=[_edge("n_trigger", "n_wait")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # waitForInput sends prompt — need a 200 response
        client = _HttpClient(resp=_Resp(200, {}))
        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_wait", "message": "price", "sender_id": "u_wait"},
        )

        assert delivered is True
        assert error is None
        assert retryable is False

        # Check the FlowRun that was created has waiting status and correct node
        added_runs = [r for r in db._added if hasattr(r, "status")]
        assert len(added_runs) >= 1
        run_obj = added_runs[-1]
        assert run_obj.status == "waiting"
        assert run_obj.current_node_id == "n_wait"

        # Prompt was sent via Graph API
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Email?"

    async def test_condition_node_picks_true_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """condition node evaluates predicate and follows true/false edge."""
        trigger = _comment_trigger_node()
        cond = _condition_node(node_id="n_cond", variable="score", operator="eq", value="high")
        send_true = _send_message_node(node_id="n_true", message="Premium!")
        send_false = _send_message_node(node_id="n_false", message="Standard.")

        flow = _make_flow(
            nodes=[trigger, cond, send_true, send_false],
            edges=[
                _edge("n_trigger", "n_cond"),
                _edge("n_cond", "n_true", handle="true"),
                _edge("n_cond", "n_false", handle="false"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))

        # Inject context so condition evaluates true
        original_flow_run_add = db.add
        captured_runs: list[Any] = []

        def _capturing_add(row: Any) -> None:
            original_flow_run_add(row)
            if hasattr(row, "context"):
                row.context = {"score": "high"}  # pre-seed context
            captured_runs.append(row)

        db.add = _capturing_add

        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_cond", "message": "price", "sender_id": "u_cond"},
        )

        assert delivered is True
        # The true branch sends "Premium!" — verify Graph POST text
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Premium!"

    async def test_condition_node_picks_false_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """condition node evaluates predicate and follows false edge when false."""
        trigger = _comment_trigger_node()
        cond = _condition_node(node_id="n_cond", variable="score", operator="eq", value="high")
        send_true = _send_message_node(node_id="n_true", message="Premium!")
        send_false = _send_message_node(node_id="n_false", message="Standard.")

        flow = _make_flow(
            nodes=[trigger, cond, send_true, send_false],
            edges=[
                _edge("n_trigger", "n_cond"),
                _edge("n_cond", "n_true", handle="true"),
                _edge("n_cond", "n_false", handle="false"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))

        # context has score="low" → condition is false → false branch
        def _capturing_add(row: Any) -> None:
            db._added.append(row)
            if hasattr(row, "context"):
                row.context = {"score": "low"}

        db.add = _capturing_add

        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_false", "message": "price", "sender_id": "u_false"},
        )

        assert delivered is True
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Standard."

    async def test_cycle_guard_marks_run_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Node visit cap exceeded → run.status='failed', returns error."""
        trigger = _comment_trigger_node()
        # Create a cycle: n_a → n_b → n_a (both sendMessage so they keep looping)
        n_a = {"id": "n_a", "type": "sendMessage", "position": {"x": 0, "y": 0}, "data": {"message": "a"}}
        n_b = {"id": "n_b", "type": "sendMessage", "position": {"x": 0, "y": 0}, "data": {"message": "b"}}
        flow = _make_flow(
            nodes=[trigger, n_a, n_b],
            edges=[
                _edge("n_trigger", "n_a"),
                _edge("n_a", "n_b"),
                _edge("n_b", "n_a"),  # cycle back
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_cycle", "message": "price", "sender_id": "u_cycle"},
        )

        assert delivered is False
        assert retryable is False
        assert error is not None and "cap" in error.lower()

        # Run must be marked failed
        added_runs = [r for r in db._added if hasattr(r, "status")]
        assert any(r.status == "failed" for r in added_runs)


# ---------------------------------------------------------------------------
# Helpers for 58.2 tests
# ---------------------------------------------------------------------------


def _ai_router_node(
    node_id: str = "n_router",
    intents: list[dict] | None = None,
    fallback_handle: str = "other",
    input_variable: str = "_input",
) -> dict:
    return {
        "id": node_id,
        "type": "aiRouter",
        "position": {"x": 200, "y": 0},
        "data": {
            "intents": intents
            or [
                {"id": "sales", "label": "Sales"},
                {"id": "support", "label": "Support"},
            ],
            "fallbackHandle": fallback_handle,
            "inputVariable": input_variable,
        },
    }


def _pause_node(
    node_id: str = "n_pause",
    duration_seconds: int = 86400,
    message: str = "",
) -> dict:
    return {
        "id": node_id,
        "type": "pause",
        "position": {"x": 200, "y": 0},
        "data": {
            "durationSeconds": duration_seconds,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# AI Router tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAiRouterNode:
    """Tests for the aiRouter node executor."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    def _make_llm_result(content: str) -> "Any":
        """Build a minimal LLMResult for mocking (all required fields)."""
        from rag.orchestrator.llm import LLMResult

        return LLMResult(
            content=content,
            model="test-model",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=0,
        )

    async def test_airouter_picks_matching_intent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """aiRouter follows the sourceHandle matching the LLM-classified intent."""
        from unittest.mock import AsyncMock
        import rag.orchestrator.llm as _llm_mod

        trigger = _comment_trigger_node(keyword="hi", match_type="contains")
        router = _ai_router_node(
            node_id="n_router",
            intents=[{"id": "sales", "label": "Sales"}, {"id": "support", "label": "Support"}],
        )
        send_sales = _send_message_node(node_id="n_sales", message="Sales here!")
        send_support = _send_message_node(node_id="n_support", message="Support here!")

        flow = _make_flow(
            nodes=[trigger, router, send_sales, send_support],
            edges=[
                _edge("n_trigger", "n_router"),
                _edge("n_router", "n_sales", handle="sales"),
                _edge("n_router", "n_support", handle="support"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # The engine does: from rag.orchestrator.llm import chat_complete
        # Patch the module attribute so the inline import picks it up.
        mock_chat = AsyncMock(return_value=TestAiRouterNode._make_llm_result("sales"))
        monkeypatch.setattr(_llm_mod, "chat_complete", mock_chat)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ai_1", "message": "hi", "sender_id": "u_ai"},
        )

        assert delivered is True
        assert error is None
        # Only the sales branch sendMessage should be sent
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Sales here!"

    async def test_airouter_garbage_llm_output_uses_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unrecognised LLM output → fallback 'other' handle is used."""
        from unittest.mock import AsyncMock
        import rag.orchestrator.llm as _llm_mod

        trigger = _comment_trigger_node(keyword="hi", match_type="contains")
        router = _ai_router_node(node_id="n_router")
        send_other = _send_message_node(node_id="n_other", message="Fallback response")

        flow = _make_flow(
            nodes=[trigger, router, send_other],
            edges=[
                _edge("n_trigger", "n_router"),
                _edge("n_router", "n_other", handle="other"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # LLM returns garbage that matches no intent
        mock_chat = AsyncMock(
            return_value=TestAiRouterNode._make_llm_result("GIBBERISH_LABEL_XYZ")
        )
        monkeypatch.setattr(_llm_mod, "chat_complete", mock_chat)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ai_2", "message": "hi", "sender_id": "u_ai2"},
        )

        assert delivered is True
        assert error is None
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Fallback response"

    async def test_airouter_llm_exception_uses_fallback_no_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chat_complete raising → fallback 'other' handle; engine does NOT crash."""
        from unittest.mock import AsyncMock
        import rag.orchestrator.llm as _llm_mod

        trigger = _comment_trigger_node(keyword="hi", match_type="contains")
        router = _ai_router_node(node_id="n_router")
        send_other = _send_message_node(node_id="n_other", message="Safe fallback")

        flow = _make_flow(
            nodes=[trigger, router, send_other],
            edges=[
                _edge("n_trigger", "n_router"),
                _edge("n_router", "n_other", handle="other"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # LLM raises an error
        mock_chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        monkeypatch.setattr(_llm_mod, "chat_complete", mock_chat)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ai_3", "message": "hi", "sender_id": "u_ai3"},
        )

        assert delivered is True
        assert error is None
        # Fallback branch should have fired
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "Safe fallback"

    async def test_airouter_injects_tenant_language_directive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase 59 — a non-English tenant gets the language directive injected
        into the aiRouter LLM system prompt."""
        from unittest.mock import AsyncMock
        import rag.orchestrator.llm as _llm_mod

        trigger = _comment_trigger_node(keyword="hi", match_type="contains")
        router = _ai_router_node(
            node_id="n_router",
            intents=[{"id": "sales", "label": "Sales"}, {"id": "support", "label": "Support"}],
        )
        send_sales = _send_message_node(node_id="n_sales", message="Sales here!")

        flow = _make_flow(
            nodes=[trigger, router, send_sales],
            edges=[
                _edge("n_trigger", "n_router"),
                _edge("n_router", "n_sales", handle="sales"),
            ],
        )
        # Tenant default language = Spanish.
        db = _db_stub(page_row=_make_page_row(), flows=[flow], tenant_language="es")
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        mock_chat = AsyncMock(return_value=TestAiRouterNode._make_llm_result("sales"))
        monkeypatch.setattr(_llm_mod, "chat_complete", mock_chat)

        client = _HttpClient(resp=_Resp(200, {}))
        await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ai_lang", "message": "hi", "sender_id": "u_lang"},
        )

        # The classifier system prompt must carry the strict Spanish directive.
        assert mock_chat.await_count == 1
        messages = mock_chat.await_args.args[0]
        system_content = messages[0]["content"]
        assert messages[0]["role"] == "system"
        assert "You must reply exclusively in Spanish." in system_content

    async def test_airouter_english_tenant_no_directive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase 59 — a default (English) tenant gets a byte-identical prompt
        with no language directive appended."""
        from unittest.mock import AsyncMock
        import rag.orchestrator.llm as _llm_mod

        trigger = _comment_trigger_node(keyword="hi", match_type="contains")
        router = _ai_router_node(node_id="n_router")
        send_sales = _send_message_node(node_id="n_sales", message="Sales here!")

        flow = _make_flow(
            nodes=[trigger, router, send_sales],
            edges=[
                _edge("n_trigger", "n_router"),
                _edge("n_router", "n_sales", handle="sales"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow], tenant_language="en")
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        mock_chat = AsyncMock(return_value=TestAiRouterNode._make_llm_result("sales"))
        monkeypatch.setattr(_llm_mod, "chat_complete", mock_chat)

        client = _HttpClient(resp=_Resp(200, {}))
        await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_ai_en", "message": "hi", "sender_id": "u_en"},
        )

        assert mock_chat.await_count == 1
        system_content = mock_chat.await_args.args[0][0]["content"]
        assert "reply exclusively in" not in system_content


# ---------------------------------------------------------------------------
# Pause node tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPauseNode:
    """Tests for the pause node executor."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    async def test_pause_node_calls_set_bot_paused_with_86400(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pause node calls set_bot_paused(duration_s=86400) and marks run completed."""
        import rag.messenger.hitl as _hitl

        trigger = _comment_trigger_node(keyword="help", match_type="contains")
        pause = _pause_node(node_id="n_pause", duration_seconds=86400)

        flow = _make_flow(
            nodes=[trigger, pause],
            edges=[_edge("n_trigger", "n_pause")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        paused_calls: list[dict] = []

        async def _mock_set_paused(sender_id: str, duration_s: int | None = None) -> None:
            paused_calls.append({"sender_id": sender_id, "duration_s": duration_s})

        # The pause executor does: from rag.messenger.hitl import set_bot_paused
        # Patching the attribute on the module intercepts the import at call time.
        monkeypatch.setattr(_hitl, "set_bot_paused", _mock_set_paused)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_pause_1", "message": "help", "sender_id": "u_pause"},
        )

        assert delivered is True
        assert error is None
        assert retryable is False

        # set_bot_paused must have been called with duration_s=86400
        assert len(paused_calls) == 1
        assert paused_calls[0]["duration_s"] == 86400
        assert paused_calls[0]["sender_id"] == "u_pause"

        # Run must be completed
        added_runs = [r for r in db._added if hasattr(r, "status")]
        assert any(r.status == "completed" for r in added_runs)

    async def test_pause_node_sends_handoff_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pause node sends the optional handoff message before completing."""
        import rag.messenger.hitl as _hitl

        trigger = _comment_trigger_node(keyword="agent", match_type="contains")
        pause = _pause_node(
            node_id="n_pause", duration_seconds=86400, message="A human will contact you soon."
        )

        flow = _make_flow(
            nodes=[trigger, pause],
            edges=[_edge("n_trigger", "n_pause")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        async def _mock_set_paused(sender_id: str, duration_s: int | None = None) -> None:
            pass

        monkeypatch.setattr(_hitl, "set_bot_paused", _mock_set_paused)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_pause_2", "message": "agent", "sender_id": "u_pause2"},
        )

        assert delivered is True
        assert error is None
        # Handoff message should have been sent via Graph API
        assert len(client.posts) == 1
        assert client.posts[0]["json"]["message"]["text"] == "A human will contact you soon."


# ---------------------------------------------------------------------------
# resume_flow_for_dm tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResumeFlowForDm:
    """Tests for the waitForInput → DM resume path."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    async def test_wait_for_input_halts_and_dm_resumes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full end-to-end: trigger → waitForInput halts → DM resumes, finishes."""
        # Phase 1: start the flow (trigger → waitForInput)
        trigger = _comment_trigger_node()
        wait = _wait_for_input_node(node_id="n_wait", prompt="Email?", variable="email")
        send_final = _send_message_node(node_id="n_final", message="Thanks!")
        flow = _make_flow(
            nodes=[trigger, wait, send_final],
            edges=[
                _edge("n_trigger", "n_wait"),
                _edge("n_wait", "n_final"),
            ],
        )
        db_start = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db_start))

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _, error, _ = await _fe.run_flow_job(
            client,
            {"page_id": "page_1", "comment_id": "c_wait2", "message": "price", "sender_id": "u_resume"},
        )

        assert delivered is True
        assert error is None
        # Run is parked at n_wait
        added_runs = [r for r in db_start._added if hasattr(r, "current_node_id")]
        assert len(added_runs) >= 1
        parked_run = added_runs[-1]
        assert parked_run.status == "waiting"
        assert parked_run.current_node_id == "n_wait"

        # Phase 2: DM arrives → resume
        # Build a FlowRun mock that mirrors the parked state
        run_mock = MagicMock()
        run_mock.id = uuid.uuid4()
        run_mock.flow_id = flow.id
        run_mock.page_id = "page_1"
        run_mock.sender_id = "u_resume"
        run_mock.current_node_id = "n_wait"
        run_mock.status = "waiting"
        run_mock.context = {}

        db_resume = _db_stub_resume(run_row=run_mock, flow_row=flow)
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db_resume))

        client2 = _HttpClient(resp=_Resp(200, {}))
        handled = await _fe.resume_flow_for_dm(
            client2,
            page_id="page_1",
            sender_id="u_resume",
            message="user@example.com",
            token="tok",
        )

        assert handled is True
        # context should have been updated with the email
        assert run_mock.context.get("email") == "user@example.com"
        # Final sendMessage was dispatched
        assert len(client2.posts) == 1
        assert client2.posts[0]["json"]["message"]["text"] == "Thanks!"
        # Run completed
        assert run_mock.status == "completed"

    async def test_no_waiting_run_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No waiting FlowRun for (page_id, sender_id) → resume returns False."""
        db = _db_stub_resume(run_row=None)
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        handled = await _fe.resume_flow_for_dm(
            _HttpClient(),
            page_id="page_1",
            sender_id="u_nobody",
            message="hello",
            token="tok",
        )

        assert handled is False


# ---------------------------------------------------------------------------
# 58.3 helper node builders
# ---------------------------------------------------------------------------


def _webhook_node(
    node_id: str = "n_webhook",
    url: str = "https://n8n.example.com/webhook/test",
    body_template: str = '{"text": "{{ _input }}"}',
) -> dict:
    return {
        "id": node_id,
        "type": "webhook",
        "position": {"x": 200, "y": 0},
        "data": {"url": url, "bodyTemplate": body_template},
    }


def _update_crm_node(
    node_id: str = "n_crm",
    action: str = "add_tag",
    value: Any = "VIP",
    field: str = "",
) -> dict:
    return {
        "id": node_id,
        "type": "updateCrm",
        "position": {"x": 200, "y": 0},
        "data": {"action": action, "value": value, "field": field},
    }


def _make_contact(
    tags: list | None = None,
    attributes: dict | None = None,
    hot_lead: bool = False,
) -> MagicMock:
    """Build a minimal FlowContact stub."""
    contact = MagicMock()
    contact.tags = list(tags or [])
    contact.attributes = dict(attributes or {})
    contact.hot_lead = hot_lead
    return contact


# ---------------------------------------------------------------------------
# Webhook node tests (Phase 58.3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWebhookNode:
    """Tests for the webhook flow node executor."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    async def test_webhook_posts_with_interpolated_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """webhook node POSTs to configured URL with {{ _input }} interpolated."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        webhook = _webhook_node(
            node_id="n_wh",
            url="https://n8n.example.com/webhook/test",
            body_template='{"text": "{{ _input }}", "sender": "{{ sender_id }}"}',
        )
        flow = _make_flow(
            nodes=[trigger, webhook],
            edges=[_edge("n_trigger", "n_wh")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_wh_1",
                "message": "price",
                "sender_id": "u_wh",
            },
        )

        assert delivered is True
        assert error is None
        assert retryable is False

        # One POST to the webhook URL (Graph sendMessage is NOT called — only webhook)
        assert len(client.posts) == 1
        post = client.posts[0]
        assert post["url"] == "https://n8n.example.com/webhook/test"
        assert post["json"]["text"] == "price"       # {{ _input }} interpolated
        assert post["json"]["sender"] == "u_wh"      # {{ sender_id }} interpolated

    async def test_webhook_non2xx_continues_traversal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Webhook returning 4xx → traversal continues (best-effort); run not failed."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        webhook = _webhook_node(node_id="n_wh", url="https://n8n.example.com/hook")
        send = _send_message_node(node_id="n_send_after", message="Done!")
        flow = _make_flow(
            nodes=[trigger, webhook, send],
            edges=[
                _edge("n_trigger", "n_wh"),
                _edge("n_wh", "n_send_after"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # Webhook returns 500 — engine must NOT dead-letter; subsequent node must fire.
        # Use a two-response client: first call returns 500, second 200.
        responses = [_Resp(500, {}), _Resp(200, {})]
        call_count = [0]

        class _TwoRespClient(_HttpClient):
            async def post(self, url, *, params=None, json=None, **kwargs):  # type: ignore[override]
                self.posts.append({"url": url, "params": params or {}, "json": json or {}})
                resp = responses[call_count[0]]
                call_count[0] += 1
                return resp

        client = _TwoRespClient()
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_wh_non2xx",
                "message": "price",
                "sender_id": "u_wh2",
            },
        )

        assert delivered is True
        assert error is None
        # Both webhook + sendMessage were called
        assert len(client.posts) == 2
        # The second call is the sendMessage POST to Graph API
        assert client.posts[1]["json"]["message"]["text"] == "Done!"

    async def test_webhook_exception_continues_traversal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """client.post raising → traversal continues; run NOT failed."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        webhook = _webhook_node(node_id="n_wh", url="https://n8n.example.com/hook")
        send = _send_message_node(node_id="n_send_after", message="Still here!")
        flow = _make_flow(
            nodes=[trigger, webhook, send],
            edges=[
                _edge("n_trigger", "n_wh"),
                _edge("n_wh", "n_send_after"),
            ],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        call_count = [0]

        class _ErrThenOkClient(_HttpClient):
            async def post(self, url, *, params=None, json=None, **kwargs):  # type: ignore[override]
                self.posts.append({"url": url, "params": params or {}, "json": json or {}})
                if call_count[0] == 0:
                    call_count[0] += 1
                    raise httpx.ConnectError("connection refused")
                call_count[0] += 1
                return _Resp(200, {})

        client = _ErrThenOkClient()
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_wh_exc",
                "message": "price",
                "sender_id": "u_wh3",
            },
        )

        assert delivered is True
        assert error is None
        # Both attempted; second is Graph sendMessage
        assert len(client.posts) == 2
        assert client.posts[1]["json"]["message"]["text"] == "Still here!"


# ---------------------------------------------------------------------------
# UpdateCrm node tests (Phase 58.3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateCrmNode:
    """Tests for the updateCrm flow node executor."""

    @pytest.fixture(autouse=True)
    def _patch_decrypt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")

    @pytest.fixture(autouse=True)
    def _patch_overlay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    async def test_add_tag_creates_contact_with_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_tag action creates a FlowContact and applies the tag."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        crm = _update_crm_node(node_id="n_crm", action="add_tag", value="VIP")
        flow = _make_flow(
            nodes=[trigger, crm],
            edges=[_edge("n_trigger", "n_crm")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        # Patch _get_or_create_contact to return a controllable contact stub.
        contact = _make_contact()
        async def _mock_get_or_create(db_arg, tenant_id, page_id, sender_id):
            return contact

        monkeypatch.setattr(_fe, "_get_or_create_contact", _mock_get_or_create)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_crm_add",
                "message": "price",
                "sender_id": "u_crm",
            },
        )

        assert delivered is True
        assert error is None
        assert "VIP" in contact.tags

    async def test_set_hot_lead_sets_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """set_hot_lead action sets hot_lead=True on the contact."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        crm = _update_crm_node(node_id="n_crm", action="set_hot_lead", value=True)
        flow = _make_flow(
            nodes=[trigger, crm],
            edges=[_edge("n_trigger", "n_crm")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        contact = _make_contact()

        async def _mock_get_or_create(db_arg, tenant_id, page_id, sender_id):
            return contact

        monkeypatch.setattr(_fe, "_get_or_create_contact", _mock_get_or_create)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_crm_hl",
                "message": "price",
                "sender_id": "u_crm2",
            },
        )

        assert delivered is True
        assert error is None
        assert contact.hot_lead is True

    async def test_remove_tag_removes_from_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """remove_tag action removes the tag from the contact's tag list."""
        trigger = _comment_trigger_node(keyword="price", match_type="exact")
        crm = _update_crm_node(node_id="n_crm", action="remove_tag", value="VIP")
        flow = _make_flow(
            nodes=[trigger, crm],
            edges=[_edge("n_trigger", "n_crm")],
        )
        db = _db_stub(page_row=_make_page_row(), flows=[flow])
        monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

        contact = _make_contact(tags=["VIP", "premium"])

        async def _mock_get_or_create(db_arg, tenant_id, page_id, sender_id):
            return contact

        monkeypatch.setattr(_fe, "_get_or_create_contact", _mock_get_or_create)

        client = _HttpClient(resp=_Resp(200, {}))
        delivered, _status, error, retryable = await _fe.run_flow_job(
            client,
            {
                "page_id": "page_1",
                "comment_id": "c_crm_rm",
                "message": "price",
                "sender_id": "u_crm3",
            },
        )

        assert delivered is True
        assert error is None
        assert "VIP" not in contact.tags
        assert "premium" in contact.tags


# ---------------------------------------------------------------------------
# Worker dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkerDispatch:
    async def test_fb_flow_target_routes_to_run_flow_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rag.messenger import worker
        from rag.messenger.queue import QueuedItem

        called: list[dict] = []

        async def _stub_job(
            client: httpx.AsyncClient, payload: dict
        ) -> tuple[bool, int | None, str | None, bool]:
            called.append(payload)
            return True, None, None, False

        import rag.messenger.flow_engine as _fe_mod

        original = getattr(_fe_mod, "run_flow_job", None)
        _fe_mod.run_flow_job = _stub_job  # type: ignore[assignment]
        try:
            item = QueuedItem(
                correlation_id="fb_flow:c_1",
                target_url="",
                payload={"page_id": "page_1", "comment_id": "c_1", "message": "price"},
                target="fb_flow",
            )
            result = await worker._send_once(httpx.AsyncClient(), item)
        finally:
            if original is not None:
                _fe_mod.run_flow_job = original  # type: ignore[assignment]

        assert result == (True, None, None, False)
        assert len(called) == 1


# ---------------------------------------------------------------------------
# Phase 58.4a — analytics instrumentation (_traverse records path + failure)
# ---------------------------------------------------------------------------


def _make_run(sender_id: str = "u_1", page_id: str = "page_1") -> Any:
    """Lightweight FlowRun double for direct _traverse calls. ``path`` starts
    as None — matching an unpersisted SQLAlchemy instance before flush."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        sender_id=sender_id,
        page_id=page_id,
        status="active",
        current_node_id=None,
        context={},
        path=None,
        failed_node_id=None,
    )


@pytest.mark.unit
class TestTraverseAnalytics:
    """_traverse records the executed node trail and the failing node id."""

    async def test_path_records_visited_nodes_on_success(self) -> None:
        trigger = _comment_trigger_node("n_trigger")
        send = _send_message_node("n_send", "Our price is $99")
        flow = _make_flow(nodes=[trigger, send], edges=[_edge("n_trigger", "n_send")])
        run = _make_run()
        client = _HttpClient(_Resp(200, {"message_id": "m1"}))

        success, error = await _fe._traverse(
            client,
            flow=flow,
            run=run,
            start_node=trigger,
            token="tok",
            db=MagicMock(),
        )

        assert success is True
        assert error is None
        assert run.status == "completed"
        assert run.path == ["n_trigger", "n_send"]
        assert run.failed_node_id is None

    async def test_failed_node_id_set_on_send_failure(self) -> None:
        trigger = _comment_trigger_node("n_trigger")
        send = _send_message_node("n_send", "boom")
        flow = _make_flow(nodes=[trigger, send], edges=[_edge("n_trigger", "n_send")])
        run = _make_run()
        client = _HttpClient(_Resp(500, {"error": {"message": "graph down"}}))

        success, _error = await _fe._traverse(
            client,
            flow=flow,
            run=run,
            start_node=trigger,
            token="tok",
            db=MagicMock(),
        )

        assert success is False
        assert run.status == "failed"
        # Failing node recorded for attribution; still present in the visited
        # path (appended before execution).
        assert run.failed_node_id == "n_send"
        assert run.path == ["n_trigger", "n_send"]
