"""Sessions CRUD: POST/GET/DELETE /sessions, /sessions/{id}.

DELETE cascades through every per-session table since SQLite FKs aren't
enabled on this schema."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _to_out, get_session_dep
from dzmm.api.schemas import SessionIn, SessionOut
from dzmm.db.models import (
    CharState,
    Feedback,
    HiddenEvent,
    Message as MessageRow,
    ModelConfig,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
    StorySummary,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


class PatchGmModelRequest(BaseModel):
    gm_model_config_id: int


class PatchSettingsRequest(BaseModel):
    narrative_polish: bool | None = None
    director_pass: bool | None = None


@router.patch("/{session_id}/settings")
async def patch_session_settings(
    session_id: int,
    body: PatchSettingsRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    import json as _json
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    settings = _json.loads(sess.settings_json or "{}")
    if body.narrative_polish is not None:
        settings["narrative_polish"] = body.narrative_polish
    if body.director_pass is not None:
        settings["director_pass"] = body.director_pass
    sess.settings_json = _json.dumps(settings)
    await s.commit()
    return {"id": sess.id, "settings": settings}


@router.get("/{session_id}/settings")
async def get_session_settings(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    import json as _json
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return {"id": sess.id, "settings": _json.loads(sess.settings_json or "{}")}


@router.patch("/{session_id}/gm_model")
async def patch_session_gm_model(
    session_id: int,
    body: PatchGmModelRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cfg = await s.get(ModelConfig, body.gm_model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")
    sess.gm_model_config_id = body.gm_model_config_id
    await s.commit()
    return {"id": sess.id, "gm_model_config_id": sess.gm_model_config_id}


@router.post("", response_model=SessionOut)
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    sess = GameSession(**body.model_dump())
    s.add(sess)
    await s.flush()
    s.add(CharState(session_id=sess.id))
    await s.commit()
    await s.refresh(sess)
    return _to_out(sess)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return _to_out(sess)


@router.get("", response_model=list[SessionOut])
async def list_sessions(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(
        select(GameSession).order_by(GameSession.last_played.desc())
    )).scalars().all()
    return [_to_out(x) for x in rows]


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int, s: AsyncSession = Depends(get_session_dep)
):
    """Delete a session and all of its associated rows: messages, NPCs, NPC
    relations, plot threads, char_state, story_summary,
    pc_goals, hidden_events, screenplays + revisions, feedbacks. The world,
    character, and model_configs are NOT touched (shared across sessions)."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # Order matters: revisions reference screenplay; everything else just
    # references session. SQLite FK cascade isn't enabled on this schema, so
    # we wipe each table explicitly.
    sp_ids = (await s.execute(
        select(Screenplay.id).where(Screenplay.session_id == session_id)
    )).scalars().all()
    if sp_ids:
        await s.execute(
            delete(ScreenplayRevision).where(
                ScreenplayRevision.screenplay_id.in_(sp_ids)
            )
        )
        await s.execute(
            delete(Screenplay).where(Screenplay.session_id == session_id)
        )

    for model in (
        MessageRow, NPC, NpcRelation, PlotThread,
        CharState, StorySummary, PCGoal, HiddenEvent, Feedback,
    ):
        await s.execute(
            delete(model).where(model.session_id == session_id)
        )

    await s.delete(sess)
    await s.commit()
    return
