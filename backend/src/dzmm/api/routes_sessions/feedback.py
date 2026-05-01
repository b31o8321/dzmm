"""Player-submitted feedback bound to a session/turn."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Feedback, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])

_FEEDBACK_KINDS = {"bug", "suggestion", "praise", "other"}


@router.post("/{session_id}/feedback")
async def post_feedback(
    session_id: int,
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    """Player-submitted feedback bound to a session. The frontend sends:
        { content: str, kind?: "bug"|"suggestion"|"praise"|"other",
          message_id?: int }
    Turn is snapshotted from session.turn_count so analysis later knows the
    exact moment in the playthrough that prompted the complaint."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content required")
    if len(content) > 4000:
        raise HTTPException(400, "content too long (max 4000 chars)")

    kind = (payload.get("kind") or "other").strip().lower()
    if kind not in _FEEDBACK_KINDS:
        kind = "other"

    msg_id = payload.get("message_id")
    if msg_id is not None:
        try:
            msg_id = int(msg_id)
        except (TypeError, ValueError):
            msg_id = None

    fb = Feedback(
        session_id=session_id,
        turn=sess.turn_count,
        message_id=msg_id,
        kind=kind,
        content=content,
    )
    s.add(fb)
    await s.commit()
    await s.refresh(fb)
    return {
        "id": fb.id,
        "session_id": fb.session_id,
        "turn": fb.turn,
        "message_id": fb.message_id,
        "kind": fb.kind,
        "content": fb.content,
        "created_at": fb.created_at.isoformat(),
    }


@router.get("/{session_id}/feedback")
async def list_feedback(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (await s.execute(
        select(Feedback).where(Feedback.session_id == session_id)
        .order_by(Feedback.created_at, Feedback.id)
    )).scalars().all()
    return [
        {
            "id": f.id,
            "turn": f.turn,
            "message_id": f.message_id,
            "kind": f.kind,
            "content": f.content,
            "created_at": f.created_at.isoformat(),
        }
        for f in rows
    ]
