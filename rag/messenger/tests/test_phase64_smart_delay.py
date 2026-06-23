"""Phase 64 — Smart Delay temporal execution.

Covers the two halves of the feature with no real DB/network:
    * ``smartDelay`` node halts ``_traverse`` with status='sleeping' + resume_at.
    * the background poller ``resume_due_flows`` claims a due run, resolves its
      token, and resumes traversal from the node after the delay.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from rag.messenger import flow_engine as _fe


# ---------------------------------------------------------------------------
# Minimal stubs (mirror test_flow_engine.py)
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _HttpClient:
    def __init__(self, resp: _Resp | None = None) -> None:
        self._resp = resp or _Resp(200)
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_HttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, *, params=None, json=None, **_: Any) -> _Resp:
        self.posts.append({"url": url, "params": params or {}, "json": json or {}})
        return self._resp


class _ExecResult:
    def __init__(self, scalar: Any = None, scalars: list | None = None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> Any:
        r = MagicMock()
        r.all.return_value = self._scalars
        return r


class _SeqDb:
    """AsyncSession double that returns a fixed sequence of execute results."""

    def __init__(self, results: list[_ExecResult]) -> None:
        self._results = results
        self.i = 0
        self.commits = 0

    async def execute(self, _stmt: Any) -> _ExecResult:
        r = self._results[self.i]
        self.i += 1
        return r

    async def commit(self) -> None:
        self.commits += 1

    def add(self, _row: Any) -> None:
        pass

    async def __aenter__(self) -> "_SeqDb":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _sessionmaker(db: Any):
    sm = MagicMock()
    sm.return_value = db
    return sm


def _delay_node(
    node_id: str = "n_delay", days: int = 0, hours: int = 0, minutes: int = 0
) -> dict:
    return {
        "id": node_id,
        "type": "smartDelay",
        "data": {"days": days, "hours": hours, "minutes": minutes},
    }


def _send_node(node_id: str = "n_send", message: str = "Done waiting!") -> dict:
    return {"id": node_id, "type": "sendMessage", "data": {"message": message}}


def _edge(src: str, tgt: str) -> dict:
    return {"id": f"e_{src}_{tgt}", "source": src, "target": tgt, "sourceHandle": None}


def _flow(nodes: list[dict], edges: list[dict]):
    return SimpleNamespace(
        id=uuid.uuid4(),
        flow_state={"nodes": nodes, "edges": edges, "viewport": None},
    )


def _run(current: str | None = None, status: str = "active"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        flow_id=uuid.uuid4(),
        status=status,
        current_node_id=current,
        resume_at=None,
        page_id="page_1",
        sender_id="u_1",
        tenant_id=uuid.uuid4(),
        context={},
        # Phase 61 — _traverse records the visited path + failed node for the
        # executions overlay; the fake run must carry these fields too.
        path=[],
        failed_node_id=None,
    )


# ---------------------------------------------------------------------------
# _delay_seconds helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delay_seconds_sums_units():
    assert (
        _fe._delay_seconds({"days": 1, "hours": 2, "minutes": 30})
        == 86400 + 7200 + 1800
    )


@pytest.mark.unit
def test_delay_seconds_clamps_and_coerces():
    assert _fe._delay_seconds({"days": 9999}) == _fe._MAX_DELAY_SECONDS
    assert _fe._delay_seconds({"hours": "bad", "minutes": -5}) == 0


# ---------------------------------------------------------------------------
# smartDelay node halts traversal
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_smart_delay_halts_sleeping():
    flow = _flow(
        nodes=[_delay_node(minutes=30), _send_node()],
        edges=[_edge("n_delay", "n_send")],
    )
    run = _run()
    before = _fe._utcnow()

    success, error = await _fe._traverse(
        _HttpClient(),
        flow=flow,
        run=run,
        start_node=flow.flow_state["nodes"][0],
        token="tok",
        db=MagicMock(),
    )

    assert success is True and error is None
    assert run.status == "sleeping"
    assert run.current_node_id == "n_delay"
    delta = (run.resume_at - before).total_seconds()
    assert 1700 <= delta <= 1900  # ~30 min


@pytest.mark.unit
async def test_zero_delay_falls_through():
    flow = _flow(
        nodes=[_delay_node(), _send_node()],  # 0d0h0m
        edges=[_edge("n_delay", "n_send")],
    )
    run = _run()
    client = _HttpClient()

    success, _ = await _fe._traverse(
        client,
        flow=flow,
        run=run,
        start_node=flow.flow_state["nodes"][0],
        token="tok",
        db=MagicMock(),
    )

    assert success is True
    assert run.status == "completed"  # ran straight through to the send + end
    assert len(client.posts) == 1  # the message was sent


@pytest.mark.unit
async def test_terminal_delay_completes_without_sleeping():
    flow = _flow(nodes=[_delay_node(minutes=10)], edges=[])  # no outgoing edge
    run = _run()

    success, _ = await _fe._traverse(
        _HttpClient(),
        flow=flow,
        run=run,
        start_node=flow.flow_state["nodes"][0],
        token="tok",
        db=MagicMock(),
    )

    assert success is True
    assert run.status == "completed"
    assert run.resume_at is None


# ---------------------------------------------------------------------------
# resume_due_flows fires the resumption (the directive's key test)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_resume_due_flows_resumes_and_completes(monkeypatch):
    monkeypatch.setattr(_fe, "decrypt_token", lambda enc: "decrypted-tok")
    monkeypatch.setattr(_fe, "current_page_access_token", lambda: "overlay-tok")

    flow = _flow(
        nodes=[_delay_node(minutes=5), _send_node()],
        edges=[_edge("n_delay", "n_send")],
    )
    run = _run(current="n_delay", status="sleeping")
    run.flow_id = flow.id
    run.resume_at = _fe._utcnow() - timedelta(seconds=1)  # overdue
    page_row = SimpleNamespace(page_access_token_enc="enc")

    # One shared db: call order is
    #   1) due-id scan, 2) claim FlowRun, 3) load NexusFlow, 4) resolve token.
    db = _SeqDb(
        [
            _ExecResult(scalars=[run.id]),
            _ExecResult(scalar=run),
            _ExecResult(scalar=flow),
            _ExecResult(scalar=page_row),
        ]
    )
    monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

    client = _HttpClient()
    resumed = await _fe.resume_due_flows(client)

    assert resumed == 1
    assert run.status == "completed"  # traversed delay→send→end
    assert run.resume_at is None
    assert len(client.posts) == 1  # the post-delay message was sent


@pytest.mark.unit
async def test_resume_due_flows_none_due(monkeypatch):
    db = _SeqDb([_ExecResult(scalars=[])])  # nothing overdue
    monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

    resumed = await _fe.resume_due_flows(_HttpClient())

    assert resumed == 0
