"""GET /sessions/{id}/locations — list of visited locations."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Location, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/locations")
async def get_locations(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (await s.execute(
        select(Location).where(Location.session_id == session_id)
        .order_by(Location.first_visited_turn, Location.id)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "first_visited_turn": r.first_visited_turn,
            "last_visited_turn": r.last_visited_turn,
            "is_current": r.is_current,
        }
        for r in rows
    ]
