"""Read-only meta endpoints: /threads, /relations.

These power the right-panel summaries; no writes happen here (all mutation
flows through state_apply tag handlers during /turn)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import (
    NpcRelation,
    PlotThread,
    Session as GameSession,
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
