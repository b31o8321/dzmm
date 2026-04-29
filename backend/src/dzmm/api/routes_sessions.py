import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import SessionIn, SessionOut, TurnRequest
from dzmm.db.models import (
    CharState,
    Message as MessageRow,
    ModelConfig,
    NPC,
    PCGoal,
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


@router.get("/{session_id}/threads")
async def get_threads(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id)
            .order_by(PlotThread.status, PlotThread.importance.desc(), PlotThread.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": t.id,
            "type": t.type,
            "description": t.description,
            "importance": t.importance,
            "status": t.status,
            "introduced_turn": t.introduced_turn,
            "resolution": t.resolution,
        }
        for t in rows
    ]


def _npc_to_dict(n: NPC) -> dict:
    try:
        affinity = json.loads(n.affinity_json or "{}")
        if not isinstance(affinity, dict):
            affinity = {}
    except (TypeError, ValueError):
        affinity = {}
    try:
        notes = json.loads(n.notes_json or "[]")
        if not isinstance(notes, list):
            notes = []
    except (TypeError, ValueError):
        notes = []
    return {
        "id": n.id,
        "name": n.name,
        "description": n.description,
        "favor": n.favor,
        "state": n.state,
        "last_seen_turn": n.last_seen_turn,
        "purpose": n.purpose,
        "archetype": n.archetype,
        "affinity": affinity,
        "pinned": bool(n.pinned),
        "notes": notes,
    }


@router.get("/{session_id}/npcs")
async def get_npcs(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return all NPCs for this session with full fields (affinity, archetype,
    purpose, pin, notes timeline). Used by the NPC roster + detail dialog."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(NPC.pinned.desc(), NPC.last_seen_turn.desc(), NPC.id.desc())
        )
    ).scalars().all()
    return [_npc_to_dict(n) for n in rows]


class PinUpdate(BaseModel):
    pinned: bool


@router.put("/{session_id}/npcs/{npc_id}/pin")
async def update_npc_pin(
    session_id: int,
    npc_id: int,
    body: PinUpdate,
    s: AsyncSession = Depends(get_session_dep),
):
    npc = await s.get(NPC, npc_id)
    if npc is None or npc.session_id != session_id:
        raise HTTPException(404, "npc not found")
    npc.pinned = bool(body.pinned)
    await s.commit()
    await s.refresh(npc)
    return _npc_to_dict(npc)


@router.put("/{session_id}/goals/{goal_id}/status")
async def update_goal_status(
    session_id: int, goal_id: int, body: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    """body: {'status': 'active'|'completed'|'abandoned', 'note'?: str}"""
    goal = await s.get(PCGoal, goal_id)
    if goal is None or goal.session_id != session_id:
        raise HTTPException(404, "goal not found")

    new_status = str(body.get("status", "")).strip().lower()
    if new_status not in ("active", "completed", "abandoned"):
        raise HTTPException(400, "invalid status")
    goal.status = new_status
    if new_status in ("completed", "abandoned"):
        sess = await s.get(GameSession, session_id)
        goal.completed_turn = sess.turn_count if sess else 0
        if "note" in body:
            goal.completion_note = str(body["note"])
    else:
        goal.completed_turn = None

    await s.commit()
    return {
        "id": goal.id, "description": goal.description, "priority": goal.priority,
        "status": goal.status, "introduced_turn": goal.introduced_turn,
        "completed_turn": goal.completed_turn, "completion_note": goal.completion_note,
    }


@router.post("/{session_id}/warmup", status_code=202)
async def warmup_model(
    session_id: int,
    session_maker = Depends(get_session_maker_dep),
):
    """Fire-and-forget: load the GM model into the runtime so the first turn
    doesn't pay the cold load cost (typically 5-20s for a 7B local model)."""
    import asyncio as _asyncio

    async def _do_warmup():
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            if cfg is None:
                return
            client = build_client(cfg)
            try:
                from dzmm.models.client import GenerationParams, Message
                async for _ in client.stream(
                    [Message(role="user", content="ok")],
                    GenerationParams(max_tokens=1, temperature=0.0),
                ):
                    pass
            except Exception:
                pass  # warmup failures are non-fatal

    _asyncio.create_task(_do_warmup())
    return {"status": "started"}


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
