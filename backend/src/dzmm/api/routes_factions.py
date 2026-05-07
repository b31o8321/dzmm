"""Factions API: list."""
import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Faction

router = APIRouter(prefix="/sessions", tags=["factions"])


def _faction_dict(f: Faction) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "ideology": f.ideology,
        "description": f.description,
        "leader_npc_id": f.leader_npc_id,
        "pc_reputation": f.pc_reputation,
        "hostile_to": json.loads(f.hostile_to_json or "[]"),
        "allied_to": json.loads(f.allied_to_json or "[]"),
    }


@router.get("/{session_id}/factions")
async def list_factions(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(
        select(Faction).where(Faction.session_id == session_id).order_by(Faction.id)
    )).scalars().all()
    return [_faction_dict(f) for f in rows]
