"""Tests for the sliding-window rate limiter.

Pipeline ops are exercised against fakeredis — same code path as
production. We override the per-minute cap via monkeypatch so tests
don't have to fire 20+ requests to hit the wall.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag.config import settings
from rag.messenger.ratelimit import enforce_rate_limit
from rag.messenger.schemas import InboundMessage


def _msg(user_id: str = "psid_rl") -> InboundMessage:
    return InboundMessage(
        user_id=user_id,
        message_text="hi",
        timestamp=1_731_742_800,
        channel="messenger",
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestRateLimit:
    async def test_under_cap_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "messenger_rate_limit_per_min", 3)
        msg = _msg()
        for _ in range(3):
            await enforce_rate_limit(msg)  # must not raise

    async def test_over_cap_raises_429(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "messenger_rate_limit_per_min", 2)
        msg = _msg()
        await enforce_rate_limit(msg)
        await enforce_rate_limit(msg)
        with pytest.raises(HTTPException) as exc_info:
            await enforce_rate_limit(msg)
        assert exc_info.value.status_code == 429
        assert exc_info.value.detail == "rate_limited"
        assert exc_info.value.headers["Retry-After"] == "60"

    async def test_disabled_when_cap_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "messenger_rate_limit_per_min", 0)
        msg = _msg()
        for _ in range(50):
            await enforce_rate_limit(msg)  # never raises

    async def test_per_user_isolation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "messenger_rate_limit_per_min", 1)
        await enforce_rate_limit(_msg("alice"))
        # Bob's first call must still succeed — separate bucket.
        await enforce_rate_limit(_msg("bob"))
        # But alice's second should fail.
        with pytest.raises(HTTPException) as exc_info:
            await enforce_rate_limit(_msg("alice"))
        assert exc_info.value.status_code == 429
