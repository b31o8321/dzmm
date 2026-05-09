"""Debug chain endpoint — per-turn LLM call trace for debug mode.

GET /sessions/{session_id}/turns/{turn_num}/debug_chain
Returns the full agent chain for a turn: Director (input+output),
Scene (input+output), NPC actors (input+output), and applied events.
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import AgentMessage, AgentStream, Message as MessageRow, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/turns/{turn_num}/debug_chain")
async def get_turn_debug_chain(
    session_id: int,
    turn_num: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """Return the complete LLM call chain for a given turn in debug format.

    Covers: player action, Director snapshot+directive, Scene prompt+output,
    each NPC actor snapshot+response, and the applied state events.
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # Player messages for this turn
    msg_rows = (await s.execute(
        select(MessageRow)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.turn == turn_num,
        )
        .order_by(MessageRow.id)
    )).scalars().all()

    player_action = ""
    gm_output = ""
    applied_events: list[dict] = []
    tok_in_total = 0
    tok_out_total = 0
    for m in msg_rows:
        if m.role == "user":
            player_action = m.content or ""
        elif m.role == "assistant":
            gm_output = m.content or ""
            tok_in_total += m.tokens_in or 0
            tok_out_total += m.tokens_out or 0
            if m.events_json:
                try:
                    applied_events = json.loads(m.events_json)
                except (ValueError, TypeError):
                    applied_events = []

    # Agent streams for this session
    streams = (await s.execute(
        select(AgentStream).where(AgentStream.session_id == session_id)
    )).scalars().all()
    stream_map: dict[str, AgentStream] = {f"{st.kind}:{st.ref}": st for st in streams}

    async def get_turn_messages(kind: str, ref: str = "") -> list[dict]:
        key = f"{kind}:{ref}"
        st = stream_map.get(key)
        if st is None:
            return []
        rows = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == st.id,
                AgentMessage.turn == turn_num,
            )
            .order_by(AgentMessage.id)
        )).scalars().all()
        return [
            {
                "role": r.role,
                "content": r.content,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "is_summary": r.is_summary,
            }
            for r in rows
        ]

    director_msgs = await get_turn_messages("gm_director")
    scene_msgs = await get_turn_messages("scene")

    # NPC actors: all streams with kind="npc"
    npc_actors = []
    for st in streams:
        if st.kind != "npc" or not st.ref:
            continue
        rows = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == st.id,
                AgentMessage.turn == turn_num,
            )
            .order_by(AgentMessage.id)
        )).scalars().all()
        if rows:
            npc_actors.append({
                "name": st.ref,
                "messages": [
                    {
                        "role": r.role,
                        "content": r.content,
                        "tokens_in": r.tokens_in,
                        "tokens_out": r.tokens_out,
                    }
                    for r in rows
                ],
            })

    return {
        "turn": turn_num,
        "player_action": player_action,
        "gm_output": gm_output,
        "tokens_in_total": tok_in_total,
        "tokens_out_total": tok_out_total,
        "director": director_msgs,
        "scene": scene_msgs,
        "npcs": npc_actors,
        "applied_events": applied_events,
    }
