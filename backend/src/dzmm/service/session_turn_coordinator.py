"""Process-local single-writer coordination for mutating game turns."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ActiveTurn:
    session_id: int
    run_id: str
    source: str
    started_at: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


class SessionBusyError(Exception):
    def __init__(self, active: ActiveTurn) -> None:
        super().__init__(f"session {active.session_id} is busy")
        self.active = active


class TurnLease:
    def __init__(self, coordinator: SessionTurnCoordinator, active: ActiveTurn) -> None:
        self._coordinator = coordinator
        self.active = active
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._coordinator.release(self.active.session_id, self.active.run_id)

    async def __aenter__(self) -> ActiveTurn:
        return self.active

    async def __aexit__(self, *_exc: object) -> None:
        await self.release()


class SessionTurnCoordinator:
    """Reserve one active mutating turn per session without queueing callers."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._active: dict[int, ActiveTurn] = {}

    async def acquire(self, session_id: int, run_id: str, source: str) -> TurnLease:
        async with self._guard:
            existing = self._active.get(session_id)
            if existing is not None:
                raise SessionBusyError(existing)
            active = ActiveTurn(
                session_id=session_id,
                run_id=run_id,
                source=source,
                started_at=datetime.now(UTC).isoformat(),
            )
            self._active[session_id] = active
            return TurnLease(self, active)

    async def release(self, session_id: int, run_id: str) -> None:
        async with self._guard:
            active = self._active.get(session_id)
            if active is not None and active.run_id == run_id:
                self._active.pop(session_id, None)

    async def get_active(self, session_id: int) -> ActiveTurn | None:
        async with self._guard:
            return self._active.get(session_id)

    async def shutdown(self) -> None:
        async with self._guard:
            self._active.clear()
