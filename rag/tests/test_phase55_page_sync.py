"""Phase 55 — Facebook Page metadata sync.

Covers: enqueue shape, Graph payload parsing, the atomic single-row updater,
and the worker job's success / auth-error / rate-limit / missing-token paths.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import rag.messenger.page_sync as ps
from rag.messenger.page_sync import (
    _parse_page_fields,
    apply_page_update,
    run_page_sync_job,
    schedule_page_sync,
)


# ---------- helpers -----------------------------------------------------------


def _page_row(*, token_enc=None, token_status="active", sync_status="ok"):
    row = MagicMock()
    row.facebook_page_id = "PAGE123"
    row.tenant_id = uuid.uuid4()
    row.page_access_token_enc = token_enc
    row.token_status = token_status
    row.sync_status = sync_status
    row.page_name = None
    row.page_about = None
    row.profile_picture_url = None
    return row


def _db_for_row(row):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _patch_sessionmaker(monkeypatch, db):
    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ps, "get_sessionmaker", lambda: lambda: _Ctx())


def _resp(status, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _client(resp):
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    return c


# ---------- enqueue + parse ---------------------------------------------------


@pytest.mark.unit
async def test_schedule_page_sync_enqueues_fb_sync(monkeypatch):
    queue = MagicMock()
    queue.enqueue = AsyncMock()
    monkeypatch.setattr(ps, "get_queue", lambda: queue)

    await schedule_page_sync("PAGE123", "name")

    queue.enqueue.assert_awaited_once()
    item = queue.enqueue.call_args.args[0]
    assert item.target == "fb_sync"
    assert item.payload == {"page_id": "PAGE123", "field": "name"}


@pytest.mark.unit
def test_parse_page_fields_extracts_name_about_picture():
    body = {
        "name": "Acme Widgets",
        "about": "We make widgets",
        "picture": {"data": {"url": "https://cdn/x.png"}},
        "id": "PAGE123",
    }
    assert _parse_page_fields(body) == {
        "name": "Acme Widgets",
        "about": "We make widgets",
        "picture": "https://cdn/x.png",
    }


@pytest.mark.unit
def test_parse_page_fields_ignores_missing():
    assert _parse_page_fields({"id": "x"}) == {}
    assert _parse_page_fields({"picture": {"data": {}}}) == {}


# ---------- atomic updater ----------------------------------------------------


@pytest.mark.unit
async def test_apply_page_update_writes_single_row():
    row = _page_row()
    db = _db_for_row(row)
    updated = await apply_page_update(
        db, "PAGE123", {"name": "New", "picture": "https://cdn/p.png"}
    )
    assert updated is True
    assert row.page_name == "New"
    assert row.profile_picture_url == "https://cdn/p.png"
    assert row.sync_status == "ok"


@pytest.mark.unit
async def test_apply_page_update_unmapped_page_dropped():
    db = _db_for_row(None)
    assert await apply_page_update(db, "GHOST", {"name": "x"}) is False


# ---------- worker job --------------------------------------------------------


@pytest.mark.unit
async def test_run_job_success_updates_and_delivers(monkeypatch):
    row = _page_row()
    db = _db_for_row(row)
    _patch_sessionmaker(monkeypatch, db)
    monkeypatch.setattr(ps, "current_page_access_token", lambda: "TOKEN")

    client = _client(
        _resp(200, {"name": "Renamed Co", "picture": {"data": {"url": "u"}}})
    )
    delivered, status, error, retryable = await run_page_sync_job(
        client, {"page_id": "PAGE123"}
    )

    assert (delivered, status, error, retryable) == (True, 200, None, False)
    assert row.page_name == "Renamed Co"
    db.commit.assert_awaited()


@pytest.mark.unit
async def test_run_job_auth_error_marks_revoked_non_retryable(monkeypatch):
    row = _page_row()
    db = _db_for_row(row)
    _patch_sessionmaker(monkeypatch, db)
    monkeypatch.setattr(ps, "current_page_access_token", lambda: "TOKEN")
    notify = AsyncMock()
    monkeypatch.setattr(ps, "_notify_token_revoked", notify)

    client = _client(_resp(401, {"error": {"code": 190, "message": "expired"}}))
    delivered, status, error, retryable = await run_page_sync_job(
        client, {"page_id": "PAGE123"}
    )

    assert delivered is False
    assert retryable is False  # token errors never retry
    assert row.token_status == "revoked"
    notify.assert_awaited_once()


@pytest.mark.unit
async def test_run_job_rate_limit_is_retryable_no_status_change(monkeypatch):
    row = _page_row()
    db = _db_for_row(row)
    _patch_sessionmaker(monkeypatch, db)
    monkeypatch.setattr(ps, "current_page_access_token", lambda: "TOKEN")

    client = _client(_resp(429, {"error": {"code": 4, "message": "throttled"}}))
    delivered, status, error, retryable = await run_page_sync_job(
        client, {"page_id": "PAGE123"}
    )

    assert delivered is False
    assert retryable is True
    assert row.token_status == "active"  # untouched on transient rate limit


@pytest.mark.unit
async def test_run_job_missing_token_invalid_non_retryable(monkeypatch):
    row = _page_row(token_enc=None)
    db = _db_for_row(row)
    _patch_sessionmaker(monkeypatch, db)
    monkeypatch.setattr(ps, "current_page_access_token", lambda: None)

    delivered, status, error, retryable = await run_page_sync_job(
        _client(_resp(200, {})), {"page_id": "PAGE123"}
    )

    assert delivered is False
    assert retryable is False
    assert row.token_status == "invalid"


@pytest.mark.unit
async def test_run_job_missing_page_id():
    delivered, status, error, retryable = await run_page_sync_job(AsyncMock(), {})
    assert delivered is False
    assert retryable is False
    assert "page_id" in error
