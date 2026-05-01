"""v0.1.0 — screenplay (outline) API endpoints."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions import get_session_dep
from dzmm.db.models import (
    ModelConfig,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
)
from dzmm.models.factory import build_client
from dzmm.service.screenplay import generate_screenplay, get_active_screenplay

router = APIRouter(prefix="/sessions", tags=["screenplay"])


def _screenplay_dict(sp: Screenplay) -> dict:
    return {
        "id": sp.id,
        "session_id": sp.session_id,
        "version": sp.version,
        "genre": sp.genre,
        "chapters": json.loads(sp.chapters_json or "[]"),
        "main_characters": json.loads(sp.main_characters_json or "[]"),
        "ending_md": sp.ending_md,
        "opening_hook": sp.opening_hook,
        "current_chapter": sp.current_chapter,
        "completed_events": json.loads(sp.completed_events_json or "[]"),
        "parent_screenplay_id": sp.parent_screenplay_id,
        "status": sp.status,
        "created_at": sp.created_at.isoformat() if sp.created_at else None,
        "concluded_at": sp.concluded_at.isoformat() if sp.concluded_at else None,
    }


# Outliner generation is a single ~2k-token LLM call. Local 7B models often
# need 90-180s; cfg.timeout (60-120s default) is too short. Override.
_OUTLINER_TIMEOUT_SECONDS = 600.0


def _build_outliner_client(cfg: ModelConfig):
    """Like build_client(cfg) but with a longer HTTP timeout suitable for
    multi-minute single-shot outline generation. Mutates a fresh client; the
    cfg row in the DB is unchanged."""
    client = build_client(cfg)
    if hasattr(client, "timeout"):
        client.timeout = max(getattr(client, "timeout", 0.0), _OUTLINER_TIMEOUT_SECONDS)
    return client


@router.post("/{session_id}/screenplay/generate")
async def generate(
    session_id: int,
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(400, "GM model config missing")
    client = _build_outliner_client(cfg)
    genre = (payload.get("genre") or "悬疑探案").strip()
    custom = (payload.get("custom_prompt") or "").strip()
    sp = await generate_screenplay(s, session_id, genre, custom, client)
    await s.commit()
    await s.refresh(sp)
    return _screenplay_dict(sp)


@router.get("/{session_id}/screenplay")
async def get_active(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        raise HTTPException(404, "no active screenplay")
    return _screenplay_dict(sp)


@router.post("/{session_id}/screenplay/mark_decision")
async def mark_decision(
    session_id: int,
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        raise HTTPException(404, "no active screenplay")
    sess = await s.get(GameSession, session_id)
    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,
        trigger_turn=sess.turn_count if sess else 0,
        trigger_description=str(payload.get("description") or "玩家手动标记")[:500],
        before_chapters_json=sp.chapters_json,
        after_chapters_json=sp.chapters_json,
        diff_summary="(player-marked, pending rewrite)",
    )
    s.add(rev)
    await s.commit()
    await s.refresh(rev)
    return {"ok": True, "revision_id": rev.id}


@router.post("/{session_id}/screenplay/continue")
async def continue_to_next(
    session_id: int,
    payload: dict | None = None,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    prev = (await s.execute(
        select(Screenplay).where(
            Screenplay.session_id == session_id,
            Screenplay.status == "concluded",
        ).order_by(Screenplay.version.desc())
    )).scalars().first()
    if prev is None:
        raise HTTPException(400, "no concluded screenplay to continue from")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(400, "GM model config missing")
    client = _build_outliner_client(cfg)
    sp = await generate_screenplay(
        s, session_id, prev.genre, prev.custom_prompt, client,
        parent_screenplay_id=prev.id,
        previous_ending=prev.ending_md,
    )
    await s.commit()
    await s.refresh(sp)
    return _screenplay_dict(sp)


@router.get("/{session_id}/screenplay/revisions")
async def list_revisions(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        return []
    rows = (await s.execute(
        select(ScreenplayRevision)
        .where(ScreenplayRevision.screenplay_id == sp.id)
        .order_by(ScreenplayRevision.created_at, ScreenplayRevision.id)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "revision_num": r.revision_num,
            "trigger_turn": r.trigger_turn,
            "trigger_description": r.trigger_description,
            "diff_summary": r.diff_summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
