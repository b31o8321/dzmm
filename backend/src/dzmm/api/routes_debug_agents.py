"""GET /sessions/{id}/agents — DebugView "Agents" tab data source."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import (
    AgentMessage,
    AgentStream,
    Session as GameSession,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

_RECENT_LIMIT = 12


@router.get("/{session_id}/agents")
async def get_session_agents(
    session_id: int, s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    streams = (await s.execute(
        select(AgentStream)
        .where(AgentStream.session_id == session_id)
        .order_by(AgentStream.kind, AgentStream.ref)
    )).scalars().all()
    out = []
    for st in streams:
        recent = (await s.execute(
            select(AgentMessage)
            .where(AgentMessage.stream_id == st.id)
            .order_by(AgentMessage.id.desc())
            .limit(_RECENT_LIMIT)
        )).scalars().all()
        recent = list(reversed(recent))
        out.append({
            "id": st.id,
            "kind": st.kind,
            "ref": st.ref,
            "last_run_turn": st.last_run_turn,
            "recent_messages": [
                {
                    "turn": m.turn, "role": m.role, "content": m.content,
                    "is_summary": bool(m.is_summary),
                }
                for m in recent
            ],
        })
    return {"session_id": session_id, "streams": out}
