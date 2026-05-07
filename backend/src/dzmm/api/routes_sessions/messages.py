"""GET /messages and GET /state — frontend hydration on page reload."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _parse_events_json, get_session_dep
from dzmm.db.models import (
    CharState,
    Message as MessageRow,
    NPC,
    PlotThread,
    Session as GameSession,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
            "events": _parse_events_json(m.events_json),
        }
        for m in rows
    ]


@router.get("/{session_id}/messages/{msg_id}/debug")
async def get_message_debug(
    session_id: int,
    msg_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    msg = await s.get(MessageRow, msg_id)
    if msg is None or msg.session_id != session_id:
        raise HTTPException(404, "message not found")
    return {
        "id": msg.id,
        "turn": msg.turn,
        "prompt_json": msg.prompt_json or "",
        "content": msg.content,
        "tokens_in": msg.tokens_in,
        "tokens_out": msg.tokens_out,
    }


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
            .where(NPC.session_id == session_id, NPC.last_seen_turn > 0)
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

    try:
        pc_mood = json.loads(sess.pc_mood_json or "{}")
        if not isinstance(pc_mood, dict):
            pc_mood = {}
    except (TypeError, ValueError):
        pc_mood = {}

    try:
        world_time = json.loads(sess.world_time_json or "{}")
        if not isinstance(world_time, dict):
            world_time = {}
    except (TypeError, ValueError):
        world_time = {}
    world_time.setdefault("day", 1)
    world_time.setdefault("period", "morning")
    world_time.setdefault("weather", "clear")

    return {
        "stats": stats,
        "inventory": inventory,
        "pc_mood": pc_mood,
        "world_time": world_time,
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
