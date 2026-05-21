"""Phase 21 — background-task registry wiring.

The default fire-and-forget scheduler must also be able to register
spawned tasks into an externally-owned set so the FastAPI lifespan can
drain them on shutdown before the Postgres checkpointer pool tears
down. The done-callback must clean up the set so completed tasks don't
leak.
"""

from __future__ import annotations

import asyncio

import pytest

from rag.messenger.routers import webhook as webhook_module


@pytest.mark.unit
@pytest.mark.asyncio
class TestTaskRegistry:
    async def test_default_scheduler_registers_into_tracker(self) -> None:
        registry: set[asyncio.Task] = set()
        webhook_module.register_task_tracker(registry)

        ran = asyncio.Event()

        async def _task() -> None:
            ran.set()

        try:
            # Hit the default scheduler directly — same path the
            # request handler uses in production.
            webhook_module._default_scheduler(_task())
            assert len(registry) == 1
            await asyncio.wait_for(ran.wait(), timeout=1.0)
            # Yield once so the done-callback runs.
            await asyncio.sleep(0)
            assert len(registry) == 0
        finally:
            webhook_module.register_task_tracker(None)

    async def test_unregistering_tracker_reverts_to_fire_and_forget(self) -> None:
        webhook_module.register_task_tracker(None)
        ran = asyncio.Event()

        async def _task() -> None:
            ran.set()

        webhook_module._default_scheduler(_task())
        await asyncio.wait_for(ran.wait(), timeout=1.0)
