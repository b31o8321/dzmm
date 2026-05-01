"""NPC roster + pin-toggle endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _npc_to_dict, get_session_dep
from dzmm.db.models import NPC, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


# v0.1.9: this exact string is the signature the NER fallback writes for stub
# NPCs (see service/state_apply/npc.py::_register_npc_ner_fallback). Used by
# the cleanup endpoint to identify rows safe to bulk-delete.
_NER_STUB_DESCRIPTION = "（GM 未补全）"


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


@router.delete("/{session_id}/npcs/auto_created", status_code=204)
async def delete_auto_created_npcs(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """v0.1.9 cleanup: drop every NER-fallback stub NPC for this session.

    Stubs are identified by the fixed sentinel description "（GM 未补全）",
    written by `_register_npc_ner_fallback`. Once the GM has run a real
    `<npc_update>` against a name, its description is replaced and the row
    is no longer eligible for cleanup. This is wired to the DebugView
    "🧹 清理 NER 自动创建" button so players can purge historical false
    positives picked up by older, looser NER thresholds."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    await s.execute(
        delete(NPC).where(
            NPC.session_id == session_id,
            NPC.description == _NER_STUB_DESCRIPTION,
        )
    )
    await s.commit()
    return Response(status_code=204)


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
