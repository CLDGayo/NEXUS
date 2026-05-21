"""Phase 21 — content-keyed idempotency + per-thread serialization lock.

The original ``check_idempotency`` (broker path) keys off the canonical
Pydantic body, which includes ``correlation_id``. That works when n8n /
Make supply a stable mid, but Meta retries with fresh mids — so this
module's new ``claim_content_idempotency`` derives the key from
*content* (sender + page + normalized text + attachment URLs + minute
bucket) instead.
"""

from __future__ import annotations

import pytest

from rag.messenger.idempotency import (
    CONTENT_CLAIM_BUCKET_S,
    acquire_thread_lock,
    claim_content_idempotency,
    content_idempotency_key,
    release_thread_lock,
)
from rag.messenger.schemas import InboundMessage


def _msg(**overrides) -> InboundMessage:
    base: dict = dict(
        user_id="psid_42",
        message_text="hello there",
        timestamp=1_731_742_800,  # epoch seconds
        channel="messenger",
        page_id="page_1",
        correlation_id="m_orig",
    )
    base.update(overrides)
    return InboundMessage(**base)


@pytest.mark.unit
class TestContentKey:
    def test_key_is_stable_across_mid_changes(self) -> None:
        a = content_idempotency_key(_msg(correlation_id="m_one"))
        b = content_idempotency_key(_msg(correlation_id="m_two"))
        assert a == b

    def test_key_is_stable_across_whitespace_and_case(self) -> None:
        a = content_idempotency_key(_msg(message_text="Hello THERE"))
        b = content_idempotency_key(_msg(message_text="  hello   there  "))
        assert a == b

    def test_different_text_produces_different_key(self) -> None:
        a = content_idempotency_key(_msg(message_text="alpha"))
        b = content_idempotency_key(_msg(message_text="beta"))
        assert a != b

    def test_different_sender_produces_different_key(self) -> None:
        a = content_idempotency_key(_msg(user_id="psid_1"))
        b = content_idempotency_key(_msg(user_id="psid_2"))
        assert a != b

    def test_different_attachment_produces_different_key(self) -> None:
        a = content_idempotency_key(
            _msg(attachments=[{"type": "image", "url": "https://a/x.jpg"}])
        )
        b = content_idempotency_key(
            _msg(attachments=[{"type": "image", "url": "https://b/y.jpg"}])
        )
        assert a != b

    def test_minute_bucket_separates_distant_retries(self) -> None:
        a = content_idempotency_key(_msg(timestamp=1_731_742_800))
        b = content_idempotency_key(
            _msg(timestamp=1_731_742_800 + CONTENT_CLAIM_BUCKET_S * 2)
        )
        assert a != b


@pytest.mark.unit
@pytest.mark.asyncio
class TestContentClaim:
    async def test_first_claim_succeeds(self) -> None:
        verdict = await claim_content_idempotency(_msg())
        assert verdict.duplicate is False

    async def test_meta_retry_with_fresh_mid_is_dedup(self) -> None:
        first = await claim_content_idempotency(_msg(correlation_id="m_first"))
        second = await claim_content_idempotency(_msg(correlation_id="m_retry"))
        assert first.duplicate is False
        assert second.duplicate is True
        assert first.key == second.key

    async def test_different_text_is_not_dedup(self) -> None:
        a = await claim_content_idempotency(_msg(message_text="a"))
        b = await claim_content_idempotency(_msg(message_text="b"))
        assert a.duplicate is False
        assert b.duplicate is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestThreadLock:
    async def test_first_acquire_succeeds(self) -> None:
        verdict = await acquire_thread_lock("psid_42")
        assert verdict.acquired is True

    async def test_second_acquire_without_release_is_blocked(self) -> None:
        a = await acquire_thread_lock("psid_42")
        b = await acquire_thread_lock("psid_42")
        assert a.acquired is True
        assert b.acquired is False

    async def test_release_allows_reacquire(self) -> None:
        a = await acquire_thread_lock("psid_42")
        assert a.acquired is True
        await release_thread_lock("psid_42")
        b = await acquire_thread_lock("psid_42")
        assert b.acquired is True

    async def test_locks_are_per_thread(self) -> None:
        a = await acquire_thread_lock("psid_1")
        b = await acquire_thread_lock("psid_2")
        assert a.acquired is True
        assert b.acquired is True
