"""PC goal listing + status update."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import PCGoal, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/goals")
async def get_goals(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
        .order_by(PCGoal.status, PCGoal.id.desc())
    )).scalars().all()
    return [
        {
            "id": g.id, "description": g.description,
            "priority": g.priority, "status": g.status,
            "introduced_turn": g.introduced_turn,
            "completed_turn": g.completed_turn,
            "completion_note": g.completion_note,
        }
        for g in rows
    ]


@router.put("/{session_id}/goals/{goal_id}/status")
async def update_goal_status(
    session_id: int, goal_id: int, body: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    """body: {'status': 'active'|'completed'|'abandoned', 'note'?: str}"""
    goal = await s.get(PCGoal, goal_id)
    if goal is None or goal.session_id != session_id:
        raise HTTPException(404, "goal not found")

    new_status = str(body.get("status", "")).strip().lower()
    if new_status not in ("active", "completed", "abandoned"):
        raise HTTPException(400, "invalid status")
    goal.status = new_status
    if new_status in ("completed", "abandoned"):
        sess = await s.get(GameSession, session_id)
        goal.completed_turn = sess.turn_count if sess else 0
        if "note" in body:
            goal.completion_note = str(body["note"])
    else:
        goal.completed_turn = None

    await s.commit()
    return {
        "id": goal.id, "description": goal.description, "priority": goal.priority,
        "status": goal.status, "introduced_turn": goal.introduced_turn,
        "completed_turn": goal.completed_turn, "completion_note": goal.completion_note,
    }
