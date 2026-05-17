"""Tests for the Redis-backed idempotency check.

Uses the autouse fakeredis fixture from conftest.py — every test gets a
fresh in-memory Redis instance, so state never leaks between cases.
"""

from __future__ import annotations

import pytest

from rag.messenger.idempotency import _key_for, check_idempotency
from rag.messenger.schemas import InboundMessage


def _msg(**overrides) -> InboundMessage:
    base = dict(
        user_id="psid_42",
        message_text="hello",
        timestamp=1_731_742_800,
        channel="messenger",
        correlation_id="corr-abc",
    )
    base.update(overrides)
    return InboundMessage(**base)


@pytest.mark.unit
class TestKeyShape:
    def test_key_includes_user_correlation_and_hash(self) -> None:
        key = _key_for(_msg())
        assert key.startswith("idemp:msgr:psid_42:corr-abc:")
        # body hash is a 16-char hex prefix
        suffix = key.split(":")[-1]
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_different_text_produces_different_key(self) -> None:
        k1 = _key_for(_msg(message_text="foo"))
        k2 = _key_for(_msg(message_text="bar"))
        assert k1 != k2

    def test_same_payload_same_key(self) -> None:
        assert _key_for(_msg()) == _key_for(_msg())

    def test_missing_correlation_id_uses_noid(self) -> None:
        key = _key_for(_msg(correlation_id=None))
        assert ":noid:" in key


@pytest.mark.unit
@pytest.mark.asyncio
class TestVerdict:
    async def test_first_request_not_duplicate(self) -> None:
        verdict = await check_idempotency(_msg())
        assert verdict.duplicate is False
        assert verdict.key

    async def test_second_identical_request_is_duplicate(self) -> None:
        msg = _msg()
        first = await check_idempotency(msg)
        second = await check_idempotency(msg)
        assert first.duplicate is False
        assert second.duplicate is True
        assert first.key == second.key

    async def test_different_correlation_id_not_duplicate(self) -> None:
        a = await check_idempotency(_msg(correlation_id="A"))
        b = await check_idempotency(_msg(correlation_id="B"))
        assert a.duplicate is False
        assert b.duplicate is False

    async def test_different_text_not_duplicate(self) -> None:
        a = await check_idempotency(_msg(message_text="alpha"))
        b = await check_idempotency(_msg(message_text="beta"))
        assert a.duplicate is False
        assert b.duplicate is False
