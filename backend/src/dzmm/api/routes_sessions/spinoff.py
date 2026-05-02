"""POST /sessions/{id}/spinoff — create a new session forking from an existing one.

Copies world_id + character_id + gm_model_config_id + summarizer_model_config_id.
Copies selected NPCs (by id list) with favor and emotion reset to neutral.
"""
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import NPC, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SpinoffRequest(BaseModel):
    name: str
    npc_ids: list[int] = []  # NPC ids to carry over (from parent session)


@router.post("/{session_id}/spinoff")
async def spinoff_session(
    session_id: int,
    body: SpinoffRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    parent = await s.get(GameSession, session_id)
    if parent is None:
        raise HTTPException(404, "session not found")

    now = datetime.now(UTC).replace(tzinfo=None)
    child = GameSession(
        name=body.name or f"{parent.name} 续",
        world_id=parent.world_id,
        character_id=parent.character_id,
        gm_model_config_id=parent.gm_model_config_id,
        summarizer_model_config_id=parent.summarizer_model_config_id,
        turn_count=0,
        created_at=now,
        last_played=now,
    )
    s.add(child)
    await s.flush()  # get child.id

    # Carry over selected NPCs with favor/emotion reset
    if body.npc_ids:
        npcs = (await s.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.id.in_(body.npc_ids))
        )).scalars().all()
        for npc in npcs:
            s.add(NPC(
                session_id=child.id,
                name=npc.name,
                description=npc.description,
                favor=0,
                state="未知",
                last_seen_turn=0,
                notes_json="[]",
                purpose=npc.purpose,
                archetype=npc.archetype,
                affinity_json="{}",
                pinned=npc.pinned,
                emotion_json="{}",
                revealed_json='{"name": true}',
            ))

    await s.commit()
    return {"id": child.id, "name": child.name}
