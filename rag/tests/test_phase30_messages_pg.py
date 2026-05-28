"""Phase 30.1 — ``_save_exchange`` writes user+assistant message pair to
Postgres via the async ORM."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from rag.database.models import Conversation, Message


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _FakeTenant:
    def __init__(self) -> None:
        self.id = uuid.UUID("4e15a5c0-7b9f-4f8e-9e30-1d000000beef")
        self.slug = "hunter"


class _FakeConversation:
    def __init__(self, conv_id: uuid.UUID) -> None:
        self.id = conv_id
        self.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)


class _StubSession:
    """AsyncSession surface enough for ``_save_exchange``."""

    def __init__(self, *, existing=None) -> None:  # noqa: ANN001
        self._existing = existing
        self.added: list[object] = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model, key):  # noqa: ANN001
        if model is Conversation and self._existing is not None:
            if self._existing.id == key:
                return self._existing
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _make_user() -> _FakeUser:
    return _FakeUser()


def _make_tenant() -> _FakeTenant:
    return _FakeTenant()


@pytest.mark.asyncio
async def test_save_exchange_inserts_new_conversation_and_message_pair() -> None:
    from rag.routers.chat import _save_exchange

    db = _StubSession()
    session_id = str(uuid.uuid4())
    await _save_exchange(
        db,
        session_id,
        question="hello?",
        answer="world.",
        sources=[{"file": "note.md", "index": 1}],
        user=_make_user(),
        tenant=_make_tenant(),
    )

    convs = [obj for obj in db.added if isinstance(obj, Conversation)]
    msgs = [obj for obj in db.added if isinstance(obj, Message)]
    assert len(convs) == 1, "expected a new Conversation insert"
    assert len(msgs) == 2, "expected the (user, assistant) pair"
    assert {m.role for m in msgs} == {"user", "assistant"}
    assistant = next(m for m in msgs if m.role == "assistant")
    assert assistant.sources == [{"file": "note.md", "index": 1}]
    assert db.commits == 1
    assert db.flushes == 1
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_save_exchange_skips_when_session_id_is_not_uuid() -> None:
    from rag.routers.chat import _save_exchange

    db = _StubSession()
    await _save_exchange(
        db,
        "not-a-uuid",
        question="hi",
        answer="hi back",
        sources=[],
        user=_make_user(),
        tenant=_make_tenant(),
    )
    assert db.added == [], "malformed session_id must not write anything"
    assert db.commits == 0


@pytest.mark.asyncio
async def test_save_exchange_touches_existing_conversation_updated_at() -> None:
    from rag.routers.chat import _save_exchange

    conv_uuid = uuid.uuid4()
    existing = _FakeConversation(conv_uuid)
    db = _StubSession(existing=existing)
    await _save_exchange(
        db,
        str(conv_uuid),
        question="next turn",
        answer="reply",
        sources=[],
        user=_make_user(),
        tenant=_make_tenant(),
    )
    assert existing.updated_at > datetime(2020, 1, 1, tzinfo=timezone.utc)
    msgs = [obj for obj in db.added if isinstance(obj, Message)]
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_save_exchange_rollback_on_exception() -> None:
    from rag.routers.chat import _save_exchange

    db = AsyncMock()
    db.get = AsyncMock(side_effect=RuntimeError("boom"))
    db.rollback = AsyncMock()

    await _save_exchange(
        db,
        str(uuid.uuid4()),
        question="q",
        answer="a",
        sources=[],
        user=_make_user(),
        tenant=_make_tenant(),
    )
    db.rollback.assert_awaited_once()
