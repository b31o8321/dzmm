"""NPC roster + pin-toggle endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _npc_to_dict, get_session_dep
from dzmm.db.models import NPC, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
