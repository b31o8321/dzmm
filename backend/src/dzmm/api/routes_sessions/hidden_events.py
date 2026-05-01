"""GM-tracked hidden events: injuries, deadlines, secrets..."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import HiddenEvent, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/hidden_events")
async def get_hidden_events(
    session_id: int,
    include_resolved: bool = False,
    s: AsyncSession = Depends(get_session_dep),
):
    """Return GM-tracked hidden events (injuries, deadlines, secrets...).
    By default only `active` rows; pass include_resolved=true for the full list."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    stmt = select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    if not include_resolved:
        stmt = stmt.where(HiddenEvent.status == "active")
    stmt = stmt.order_by(HiddenEvent.introduced_turn, HiddenEvent.id)
    rows = (await s.execute(stmt)).scalars().all()
    return [
        {
            "id": h.id,
            "subject": h.subject,
            "kind": h.kind,
            "severity": h.severity,
            "description": h.description,
            "consequence": h.consequence,
            "introduced_turn": h.introduced_turn,
            "status": h.status,
        }
        for h in rows
    ]
