import asyncio

import pytest

from dzmm.service.session_turn_coordinator import (
    SessionBusyError,
    SessionTurnCoordinator,
)


@pytest.mark.asyncio
async def test_same_session_returns_active_run_without_waiting():
    coordinator = SessionTurnCoordinator()
    first = await coordinator.acquire(42, "run-1", "turn_run")

    with pytest.raises(SessionBusyError) as raised:
        await coordinator.acquire(42, "run-2", "turn")

    assert raised.value.active.to_dict() == {
        "session_id": 42,
        "run_id": "run-1",
        "source": "turn_run",
        "started_at": raised.value.active.started_at,
    }
    await first.release()


@pytest.mark.asyncio
async def test_different_sessions_can_hold_turns_concurrently():
    coordinator = SessionTurnCoordinator()
    first, second = await asyncio.gather(
        coordinator.acquire(1, "run-1", "turn_run"),
        coordinator.acquire(2, "run-2", "turn_run"),
    )

    assert (await coordinator.get_active(1)).run_id == "run-1"
    assert (await coordinator.get_active(2)).run_id == "run-2"
    await asyncio.gather(first.release(), second.release())


@pytest.mark.asyncio
async def test_cancelled_owner_releases_its_session():
    coordinator = SessionTurnCoordinator()
    entered = asyncio.Event()

    async def owner() -> None:
        async with await coordinator.acquire(7, "run-7", "turn_run"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await coordinator.get_active(7) is None
    replacement = await coordinator.acquire(7, "run-8", "turn")
    await replacement.release()


@pytest.mark.asyncio
async def test_shutdown_clears_active_turns():
    coordinator = SessionTurnCoordinator()
    await coordinator.acquire(9, "run-9", "npc_tick")

    await coordinator.shutdown()

    assert await coordinator.get_active(9) is None
