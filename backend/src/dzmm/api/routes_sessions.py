import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import SessionIn, SessionOut, TurnRequest
from dzmm.db.models import (
    CharState,
    ModelConfig,
    Session as GameSession,
)
from dzmm.models.factory import build_client
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn
from dzmm.service.summarizer import maybe_summarize

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_dep():
    raise RuntimeError("override")


def get_session_maker_dep():
    raise RuntimeError("override")


def _to_out(s: GameSession) -> SessionOut:
    return SessionOut(
        id=s.id, name=s.name, world_id=s.world_id, character_id=s.character_id,
        gm_model_config_id=s.gm_model_config_id,
        summarizer_model_config_id=s.summarizer_model_config_id,
        turn_count=s.turn_count,
    )


@router.post("", response_model=SessionOut)
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    sess = GameSession(**body.model_dump())
    s.add(sess)
    await s.flush()
    s.add(CharState(session_id=sess.id))
    await s.commit()
    await s.refresh(sess)
    return _to_out(sess)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return _to_out(sess)


@router.get("", response_model=list[SessionOut])
async def list_sessions(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(
        select(GameSession).order_by(GameSession.last_played.desc())
    )).scalars().all()
    return [_to_out(x) for x in rows]


@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,
    session_maker = Depends(get_session_maker_dep),
):
    async def event_stream() -> AsyncIterator[dict]:
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                yield {"event": "error",
                       "data": json.dumps({"message": "session not found"})}
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            client = build_client(cfg)

            async for ev in run_turn(s, session_id, body.action, client):
                if isinstance(ev, NarrativeDelta):
                    yield {"event": "narrative",
                           "data": json.dumps({"text": ev.text}, ensure_ascii=False)}
                elif isinstance(ev, TagComplete):
                    yield {"event": "tag",
                           "data": json.dumps({"name": ev.name, "attrs": ev.attrs,
                                               "content": ev.content},
                                              ensure_ascii=False)}
                elif isinstance(ev, ParseError):
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message},
                                              ensure_ascii=False)}

            await s.commit()

        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            sum_cfg = await s.get(ModelConfig, sess.summarizer_model_config_id)
            sum_client = build_client(sum_cfg)
            try:
                ran = await maybe_summarize(s, session_id, sum_client)
                if ran:
                    await s.commit()
            except Exception as e:  # noqa: BLE001
                yield {"event": "summarize_error",
                       "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())
