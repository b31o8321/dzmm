"""Persistence helpers for idempotent remote turn runs."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.db.models import Session as GameSession, TurnRun
from dzmm.service.session_turn_coordinator import (
    SessionTurnCoordinator,
    TurnLease,
)


@dataclass(frozen=True)
class TurnEvent:
    id: int
    event: str
    data: str

    def to_sse(self) -> dict[str, str]:
        return {"id": str(self.id), "event": self.event, "data": self.data}


class EventGapError(Exception):
    def __init__(
        self,
        requested_id: int,
        earliest_id: int | None,
        latest_id: int | None,
    ) -> None:
        super().__init__("requested events are no longer available")
        self.requested_id = requested_id
        self.earliest_id = earliest_id
        self.latest_id = latest_id


class SessionNotFoundError(Exception):
    pass


class RunEventHub:
    """Bounded replay plus live fan-out for one detached producer."""

    def __init__(self, buffer_size: int = 512) -> None:
        self._events: deque[TurnEvent] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue[TurnEvent | None]] = set()
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._terminal = False

    @property
    def terminal(self) -> bool:
        return self._terminal

    async def publish(self, event: str, data: str) -> TurnEvent:
        async with self._lock:
            item = TurnEvent(self._next_id, event, data)
            self._next_id += 1
            self._events.append(item)
            for queue in self._subscribers:
                queue.put_nowait(item)
            return item

    async def close(self) -> None:
        async with self._lock:
            if self._terminal:
                return
            self._terminal = True
            for queue in self._subscribers:
                queue.put_nowait(None)
            self._subscribers.clear()

    async def subscribe(self, last_event_id: int) -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        async with self._lock:
            earliest = self._events[0].id if self._events else None
            latest = self._events[-1].id if self._events else 0
            if (
                (earliest is not None and last_event_id < earliest - 1)
                or last_event_id > latest
            ):
                raise EventGapError(last_event_id, earliest, latest)
            for event in self._events:
                if event.id > last_event_id:
                    queue.put_nowait(event)
            if self._terminal:
                queue.put_nowait(None)
            else:
                self._subscribers.add(queue)

        async def iterate() -> AsyncIterator[dict[str, str]]:
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        return
                    yield event.to_sse()
            finally:
                async with self._lock:
                    self._subscribers.discard(queue)

        return iterate()


ProducerFactory = Callable[[], AsyncIterator[dict]]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def turn_run_payload(run: TurnRun) -> dict[str, object]:
    return {
        "run_id": run.id,
        "session_id": run.session_id,
        "request_id": run.request_id,
        "action": run.action,
        "status": run.status,
        "created_at": run.created_at.isoformat() + "Z",
        "started_at": run.started_at.isoformat() + "Z",
        "completed_at": (
            run.completed_at.isoformat() + "Z" if run.completed_at else None
        ),
        "error_code": run.error_code,
        "error_message": run.error_message,
        "assistant_message_id": run.assistant_message_id,
    }


async def get_turn_run(session: AsyncSession, run_id: str) -> TurnRun | None:
    return await session.get(TurnRun, run_id)


async def get_turn_run_by_request(
    session: AsyncSession,
    session_id: int,
    request_id: str,
) -> TurnRun | None:
    return (
        await session.execute(
            select(TurnRun).where(
                TurnRun.session_id == session_id,
                TurnRun.request_id == request_id,
            )
        )
    ).scalar_one_or_none()


async def create_or_get_turn_run(
    session: AsyncSession,
    *,
    session_id: int,
    request_id: str,
    action: str,
    run_id: str | None = None,
) -> tuple[TurnRun, bool]:
    existing = await get_turn_run_by_request(session, session_id, request_id)
    if existing is not None:
        return existing, False

    run = TurnRun(
        id=run_id or str(uuid.uuid4()),
        session_id=session_id,
        request_id=request_id,
        action=action,
        status="running",
    )
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_turn_run_by_request(session, session_id, request_id)
        if existing is None:
            raise
        return existing, False
    await session.refresh(run)
    return run, True


async def finish_turn_run(
    session: AsyncSession,
    run_id: str,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    assistant_message_id: int | None = None,
) -> TurnRun | None:
    run = await get_turn_run(session, run_id)
    if run is None:
        return None
    run.status = status
    run.completed_at = _now()
    run.error_code = error_code
    run.error_message = error_message
    run.assistant_message_id = assistant_message_id
    await session.commit()
    await session.refresh(run)
    return run


async def mark_stale_turn_runs_interrupted(
    session_maker: async_sessionmaker[AsyncSession],
) -> int:
    async with session_maker() as session:
        result = await session.execute(
            update(TurnRun)
            .where(TurnRun.status == "running")
            .values(
                status="interrupted",
                completed_at=_now(),
                error_code="run_interrupted",
                error_message="The backend restarted before this turn completed",
            )
        )
        await session.commit()
        return result.rowcount or 0


class TurnRunManager:
    """Create idempotent runs and supervise producers independently of SSE clients."""

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        coordinator: SessionTurnCoordinator,
        *,
        buffer_size: int = 512,
        retained_runs: int = 32,
    ) -> None:
        self._session_maker = session_maker
        self._coordinator = coordinator
        self._buffer_size = buffer_size
        self._retained_runs = retained_runs
        self._create_guard = asyncio.Lock()
        self._hubs: dict[str, RunEventHub] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._leases: dict[str, TurnLease] = {}

    async def create_or_get(
        self,
        *,
        session_id: int,
        request_id: str,
        action: str,
        producer_factory: ProducerFactory,
    ) -> tuple[dict[str, object], bool]:
        async with self._create_guard:
            async with self._session_maker() as session:
                existing = await get_turn_run_by_request(
                    session, session_id, request_id
                )
                if existing is not None:
                    return turn_run_payload(existing), False
                if await session.get(GameSession, session_id) is None:
                    raise SessionNotFoundError(session_id)

            run_id = str(uuid.uuid4())
            lease = await self._coordinator.acquire(
                session_id, run_id, "turn_run"
            )
            try:
                async with self._session_maker() as session:
                    run, created = await create_or_get_turn_run(
                        session,
                        session_id=session_id,
                        request_id=request_id,
                        action=action,
                        run_id=run_id,
                    )
            except BaseException:
                await lease.release()
                raise

            if not created:
                await lease.release()
                return turn_run_payload(run), False

            self._prune_hubs()
            hub = RunEventHub(self._buffer_size)
            self._hubs[run.id] = hub
            self._leases[run.id] = lease
            task = asyncio.create_task(
                self._produce(run.id, producer_factory, hub, lease),
                name=f"turn-run-{run.id}",
            )
            self._tasks[run.id] = task
            task.add_done_callback(lambda _task: self._tasks.pop(run.id, None))
            return turn_run_payload(run), True

    def _prune_hubs(self) -> None:
        if len(self._hubs) < self._retained_runs:
            return
        for run_id, hub in list(self._hubs.items()):
            if hub.terminal:
                self._hubs.pop(run_id, None)
            if len(self._hubs) < self._retained_runs:
                return

    async def _finish(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        assistant_message_id: int | None = None,
    ) -> None:
        async with self._session_maker() as session:
            await finish_turn_run(
                session,
                run_id,
                status=status,
                error_code=error_code,
                error_message=error_message,
                assistant_message_id=assistant_message_id,
            )

    async def _produce(
        self,
        run_id: str,
        producer_factory: ProducerFactory,
        hub: RunEventHub,
        lease: TurnLease,
    ) -> None:
        assistant_message_id: int | None = None
        error_code: str | None = None
        error_message: str | None = None
        terminal_event: tuple[str, str] | None = None
        try:
            async for event in producer_factory():
                name = str(event.get("event", "message"))
                raw_data = event.get("data", "")
                data = raw_data if isinstance(raw_data, str) else json.dumps(raw_data)
                if name not in {"done", "error"}:
                    await hub.publish(name, data)
                    continue
                terminal_event = (name, data)
                try:
                    payload = json.loads(data)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if name == "done":
                    assistant_message_id = payload.get("assistant_msg_id")
                else:
                    error_code = payload.get("code") or "model_error"
                    error_message = payload.get("message") or "Turn generation failed"

            if error_code:
                await self._finish(
                    run_id,
                    status="failed",
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                await self._finish(
                    run_id,
                    status="completed",
                    assistant_message_id=assistant_message_id,
                )
        except asyncio.CancelledError:
            await self._finish(
                run_id,
                status="interrupted",
                error_code="run_interrupted",
                error_message="The backend stopped before this turn completed",
            )
            terminal_event = (
                "error",
                json.dumps({
                    "code": "run_interrupted",
                    "message": "The backend stopped before this turn completed",
                }),
            )
            raise
        except Exception as exc:  # noqa: BLE001
            await self._finish(
                run_id,
                status="failed",
                error_code="model_error",
                error_message=str(exc),
            )
            terminal_event = (
                "error",
                json.dumps({"code": "model_error", "message": str(exc)}),
            )
        finally:
            self._leases.pop(run_id, None)
            await lease.release()
            if terminal_event is not None:
                await hub.publish(*terminal_event)
            await hub.close()

    async def subscribe(
        self, run_id: str, last_event_id: int
    ) -> AsyncIterator[dict[str, str]]:
        hub = self._hubs.get(run_id)
        if hub is None:
            raise EventGapError(last_event_id, None, None)
        return await hub.subscribe(last_event_id)

    async def wait(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        task_items = list(self._tasks.items())
        tasks = [task for _, task in task_items]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for run_id, _task in task_items:
            async with self._session_maker() as session:
                run = await get_turn_run(session, run_id)
                still_running = run is not None and run.status == "running"
            if still_running:
                await self._finish(
                    run_id,
                    status="interrupted",
                    error_code="run_interrupted",
                    error_message="The backend stopped before this turn completed",
                )
            hub = self._hubs.get(run_id)
            if hub is not None and not hub.terminal:
                await hub.publish(
                    "error",
                    json.dumps(
                        {
                            "code": "run_interrupted",
                            "message": "The backend stopped before this turn completed",
                        }
                    ),
                )
                await hub.close()
            lease = self._leases.pop(run_id, None)
            if lease is not None:
                await lease.release()
