"""Read-only meta endpoints: /threads, /timeline, /eras, /relations.

These power the right-panel summaries; no writes happen here (all mutation
flows through state_apply tag handlers during /turn)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import (
    Era,
    Message,
    NpcRelation,
    PlotThread,
    Session as GameSession,
    Timeline,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


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


@router.get("/{session_id}/threads/{thread_id}")
async def get_thread_detail(
    session_id: int,
    thread_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """Return one plot thread's details."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    thread = await s.get(PlotThread, thread_id)
    if thread is None or thread.session_id != session_id:
        raise HTTPException(404, "thread not found")

    # Find messages around the thread's introduced_turn (±2 turns)
    lo = max(0, thread.introduced_turn - 1)
    hi = thread.introduced_turn + 2
    msgs = (await s.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.turn >= lo, Message.turn <= hi)
        .order_by(Message.turn, Message.id)
    )).scalars().all()

    return {
        "id": thread.id,
        "type": thread.type,
        "description": thread.description,
        "importance": thread.importance,
        "status": thread.status,
        "introduced_turn": thread.introduced_turn,
        "resolution": thread.resolution,
        "context_messages": [
            {"role": m.role, "content": m.content[:500], "turn": m.turn}
            for m in msgs
        ],
    }


@router.get("/{session_id}/timeline")
async def get_timeline(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (await s.execute(
        select(Timeline).where(Timeline.session_id == session_id)
        .order_by(Timeline.turn, Timeline.id)
    )).scalars().all()
    return [
        {
            "id": t.id, "turn": t.turn, "event_text": t.event_text,
            "importance": t.importance,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


@router.get("/{session_id}/eras")
async def get_eras(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (await s.execute(
        select(Era).where(Era.session_id == session_id)
        .order_by(Era.started_turn, Era.id)
    )).scalars().all()
    return [
        {"id": e.id, "name": e.name, "started_turn": e.started_turn,
         "description": e.description}
        for e in rows
    ]


@router.get("/{session_id}/relations")
async def get_relations(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return all NPC↔NPC relations registered via <npc_relation> for this session."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(NpcRelation)
            .where(NpcRelation.session_id == session_id)
            .order_by(NpcRelation.introduced_turn.desc(), NpcRelation.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "npc_a": r.npc_a,
            "npc_b": r.npc_b,
            "kind": r.kind,
            "description": r.description,
            "introduced_turn": r.introduced_turn,
        }
        for r in rows
    ]
