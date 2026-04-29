import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import SessionIn, SessionOut, TurnRequest
from dzmm.db.models import (
    CharState,
    Message as MessageRow,
    ModelConfig,
    NPC,
    PlotThread,
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


@router.get("/{session_id}/messages")
async def get_messages(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return full message history for a session, ordered chronologically.
    Used by the frontend to rehydrate the conversation log on page reload."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id)
        )
    ).scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "turn": m.turn,
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
        }
        for m in rows
    ]


@router.get("/{session_id}/state")
async def get_state(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return current PC state, NPCs, and active plot threads.
    Used by the frontend to rehydrate the right-side StatePanel on reload."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    cs = (
        await s.execute(select(CharState).where(CharState.session_id == session_id))
    ).scalar_one_or_none()
    stats: dict = {}
    inventory: list[str] = []
    if cs is not None:
        stats = json.loads(cs.stats_json or "{}")
        inventory = json.loads(cs.inventory_json or "[]")

    npc_rows = (
        await s.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
        )
    ).scalars().all()

    thread_rows = (
        await s.execute(
            select(PlotThread)
            .where(
                PlotThread.session_id == session_id,
                PlotThread.status == "active",
            )
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())
        )
    ).scalars().all()

    return {
        "stats": stats,
        "inventory": inventory,
        "npcs": [
            {"name": n.name, "favor": n.favor, "state": n.state}
            for n in npc_rows
        ],
        "threads": [
            {
                "type": t.type,
                "description": t.description,
                "importance": t.importance,
            }
            for t in thread_rows
        ],
    }


@router.delete("/{session_id}/last_turn", status_code=204)
async def delete_last_turn(
    session_id: int, s: AsyncSession = Depends(get_session_dep)
):
    """Remove the most recent user/assistant message pair and decrement
    turn_count. Frontend uses this for the regenerate / edit-last actions."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if sess.turn_count <= 0:
        return  # nothing to delete

    rows = (
        await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id.desc())
            .limit(2)
        )
    ).scalars().all()
    for r in rows:
        await s.delete(r)
    sess.turn_count = max(0, sess.turn_count - 1)
    await s.commit()


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

            import time as _time
            narrative_buf: list[str] = []
            last_flush = _time.monotonic()
            FLUSH_CHARS = 20
            FLUSH_INTERVAL = 0.05  # 50ms

            def _flush_narrative():
                if narrative_buf:
                    payload = "".join(narrative_buf)
                    narrative_buf.clear()
                    return {"event": "narrative",
                            "data": json.dumps({"text": payload}, ensure_ascii=False)}
                return None

            async for ev in run_turn(s, session_id, body.action, client):
                if isinstance(ev, NarrativeDelta):
                    narrative_buf.append(ev.text)
                    now = _time.monotonic()
                    total = sum(len(x) for x in narrative_buf)
                    if total >= FLUSH_CHARS or (now - last_flush) >= FLUSH_INTERVAL:
                        out = _flush_narrative()
                        if out:
                            yield out
                        last_flush = now
                elif isinstance(ev, TagComplete):
                    out = _flush_narrative()
                    if out:
                        yield out
                    last_flush = _time.monotonic()
                    yield {"event": "tag",
                           "data": json.dumps({"name": ev.name, "attrs": ev.attrs,
                                               "content": ev.content},
                                              ensure_ascii=False)}
                elif isinstance(ev, ParseError):
                    out = _flush_narrative()
                    if out:
                        yield out
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message},
                                              ensure_ascii=False)}

            # Flush any tail buffer before commit + cleanup.
            out = _flush_narrative()
            if out:
                yield out

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
