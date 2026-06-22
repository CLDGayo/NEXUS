"""Phase 65 — Audience CRM + UserInput node.

Two surfaces, no real DB/network:
    * ``userInput`` flow node: on DM resume, the captured reply is persisted to
      the durable ``flow_contacts`` custom-fields store (``attributes[fieldKey]``).
    * the Audience router: tenant-scoped list + merge-patch (incl. null-deletes).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import rag.routers.audience as _aud
from rag.messenger import flow_engine as _fe
from rag.routers.audience import AudiencePatch, list_audience, update_audience


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _HttpClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_HttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, *, params=None, json=None, **_: Any) -> _Resp:
        self.posts.append({"url": url})
        return _Resp(200)


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
    def __init__(self, results: list[_ExecResult]) -> None:
        self._results = results
        self.i = 0

    async def execute(self, _stmt: Any) -> _ExecResult:
        r = self._results[self.i]
        self.i += 1
        return r

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass

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


# ---------------------------------------------------------------------------
# userInput node persists captured reply to flow_contacts
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_user_input_persists_reply_to_custom_field(monkeypatch):
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        flow_state={
            "nodes": [
                {
                    "id": "n_ui",
                    "type": "userInput",
                    "data": {"fieldKey": "email", "variable": "email"},
                }
            ],
            "edges": [],  # no outgoing edge → completes after capture
        },
    )
    run_row = SimpleNamespace(
        id=uuid.uuid4(),
        flow_id=flow.id,
        status="waiting",
        current_node_id="n_ui",
        context={},
        tenant_id=uuid.uuid4(),
        page_id="page_1",
        sender_id="u_1",
    )
    contact = SimpleNamespace(attributes={})
    monkeypatch.setattr(_fe, "_get_or_create_contact", AsyncMock(return_value=contact))

    db = _SeqDb([_ExecResult(scalar=run_row), _ExecResult(scalar=flow)])
    monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

    resumed = await _fe.resume_flow_for_dm(
        _HttpClient(),
        page_id="page_1",
        sender_id="u_1",
        message="me@example.com",
        token="tok",
    )

    assert resumed is True
    assert contact.attributes["email"] == "me@example.com"  # durable persist
    assert run_row.context["email"] == "me@example.com"  # context too
    assert run_row.status == "completed"  # no edge after the node


@pytest.mark.unit
async def test_wait_for_input_does_not_persist(monkeypatch):
    """A plain waitForInput must NOT touch flow_contacts."""
    flow = SimpleNamespace(
        id=uuid.uuid4(),
        flow_state={
            "nodes": [
                {"id": "n_w", "type": "waitForInput", "data": {"variable": "email"}}
            ],
            "edges": [],
        },
    )
    run_row = SimpleNamespace(
        id=uuid.uuid4(),
        flow_id=flow.id,
        status="waiting",
        current_node_id="n_w",
        context={},
        tenant_id=uuid.uuid4(),
        page_id="page_1",
        sender_id="u_1",
    )
    persist = AsyncMock()
    monkeypatch.setattr(_fe, "_get_or_create_contact", persist)
    db = _SeqDb([_ExecResult(scalar=run_row), _ExecResult(scalar=flow)])
    monkeypatch.setattr(_fe, "get_sessionmaker", lambda: _sessionmaker(db))

    await _fe.resume_flow_for_dm(
        _HttpClient(), page_id="page_1", sender_id="u_1", message="x", token="tok"
    )

    persist.assert_not_awaited()


# ---------------------------------------------------------------------------
# Audience router
# ---------------------------------------------------------------------------


def _contact(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        page_id="page_1",
        sender_id="u_1",
        tags=["vip"],
        attributes={"email": "a@x.com", "name": "Ada"},
        hot_lead=False,
        created_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 21, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.unit
async def test_list_audience_serializes_and_paginates():
    tenant = SimpleNamespace(id=uuid.uuid4())
    rows = [_contact(), _contact(sender_id="u_2", attributes={})]
    db = _SeqDb([_ExecResult(scalar=2), _ExecResult(scalars=rows)])

    out = await list_audience(
        tenant=tenant, db=db, limit=50, offset=0, q=None, hot_lead=None
    )

    assert out["total"] == 2
    assert len(out["contacts"]) == 2
    first = out["contacts"][0]
    assert first["name"] == "Ada"  # surfaced from attributes
    assert first["custom_fields"]["email"] == "a@x.com"
    assert first["tags"] == ["vip"]
    assert "last_interaction_at" in first


@pytest.mark.unit
async def test_update_audience_merges_fields_and_null_deletes():
    tenant = SimpleNamespace(id=uuid.uuid4())
    contact = _contact()
    contact.tenant_id = tenant.id
    db = _SeqDb([_ExecResult(scalar=contact)])

    body = AudiencePatch(
        custom_fields={"plan": "pro", "name": None},  # add plan, delete name
        hot_lead=True,
        tags=["vip", "lead"],
    )
    out = await update_audience(contact_id=contact.id, body=body, tenant=tenant, db=db)

    assert contact.attributes["plan"] == "pro"
    assert "name" not in contact.attributes  # null deleted it
    assert contact.attributes["email"] == "a@x.com"  # untouched key preserved
    assert contact.hot_lead is True
    assert out["hot_lead"] is True
    assert sorted(out["tags"]) == ["lead", "vip"]


@pytest.mark.unit
async def test_update_audience_404_when_missing():
    from fastapi import HTTPException

    tenant = SimpleNamespace(id=uuid.uuid4())
    db = _SeqDb([_ExecResult(scalar=None)])
    with pytest.raises(HTTPException) as exc:
        await update_audience(
            contact_id=uuid.uuid4(),
            body=AudiencePatch(hot_lead=True),
            tenant=tenant,
            db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.unit
async def test_update_audience_422_when_empty():
    from fastapi import HTTPException

    tenant = SimpleNamespace(id=uuid.uuid4())
    contact = _contact()
    contact.tenant_id = tenant.id
    db = _SeqDb([_ExecResult(scalar=contact)])
    with pytest.raises(HTTPException) as exc:
        await update_audience(
            contact_id=contact.id, body=AudiencePatch(), tenant=tenant, db=db
        )
    assert exc.value.status_code == 422


def test_serialize_falls_back_to_underscore_keys():
    c = _contact(
        attributes={"_name": "Bob", "_avatar": "http://x/p.png", "tier": "gold"}
    )
    out = _aud._serialize(c)
    assert out["name"] == "Bob"
    assert out["profile_picture_url"] == "http://x/p.png"
    assert out["custom_fields"]["tier"] == "gold"
