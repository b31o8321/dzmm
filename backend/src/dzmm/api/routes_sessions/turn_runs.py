"""Detached, idempotent and replayable turn-run transport."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from dzmm.api.routes_sessions.turn import stream_turn_events
from dzmm.remote.turn_runs import (
    EventGapError,
    SessionNotFoundError,
    get_turn_run,
    turn_run_payload,
)
from dzmm.service.session_turn_coordinator import SessionBusyError

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateTurnRunRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=20_000)


def _error(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, **extra},
    )


@router.post("/{session_id}/turn-runs")
async def create_turn_run(
    session_id: int,
    body: CreateTurnRunRequest,
    request: Request,
):
    manager = request.app.state.turn_run_manager
    session_maker = request.app.state.turn_run_session_maker
    try:
        payload, _created = await manager.create_or_get(
            session_id=session_id,
            request_id=body.request_id,
            action=body.action,
            producer_factory=lambda: stream_turn_events(
                session_maker, session_id, body.action
            ),
        )
    except SessionNotFoundError:
        return _error(404, "session_not_found", "Session not found")
    except SessionBusyError as exc:
        return _error(
            409,
            "session_busy",
            "This session already has an active turn",
            active_run=exc.active.to_dict(),
        )
    return JSONResponse(status_code=202, content=payload)


@router.get("/{session_id}/turn-runs/{run_id}")
async def read_turn_run(session_id: int, run_id: str, request: Request):
    session_maker = request.app.state.turn_run_session_maker
    async with session_maker() as session:
        run = await get_turn_run(session, run_id)
        if run is None or run.session_id != session_id:
            return _error(404, "run_not_found", "Turn run not found")
        return turn_run_payload(run)


@router.get("/{session_id}/turn-runs/{run_id}/events")
async def turn_run_events(
    session_id: int,
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    session_maker = request.app.state.turn_run_session_maker
    async with session_maker() as session:
        run = await get_turn_run(session, run_id)
        if run is None or run.session_id != session_id:
            return _error(404, "run_not_found", "Turn run not found")

    try:
        cursor = int(last_event_id) if last_event_id is not None else 0
        if cursor < 0:
            raise ValueError
    except ValueError:
        return _error(400, "invalid_last_event_id", "Last-Event-ID must be a non-negative integer")

    try:
        events = await request.app.state.turn_run_manager.subscribe(run_id, cursor)
    except EventGapError as exc:
        return _error(
            409,
            "event_gap",
            "Requested turn events are no longer available; reload session state",
            requested_id=exc.requested_id,
            earliest_id=exc.earliest_id,
            latest_id=exc.latest_id,
        )
    return EventSourceResponse(events)
