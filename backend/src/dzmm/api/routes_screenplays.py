"""Standalone Screenplay CRUD: independent of session lifecycle."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.api.schemas import ScreenplayStandaloneIn, ScreenplayStandaloneOut
from dzmm.db.models import Screenplay, ScreenplayRevision, Session as SessionModel, World

router = APIRouter(tags=["screenplays"])


def _sp_to_out(sp: Screenplay) -> ScreenplayStandaloneOut:
    return ScreenplayStandaloneOut(
        id=sp.id,
        world_id=sp.world_id,
        session_id=sp.session_id,
        title=sp.title,
        genre=sp.genre,
        pc_name=sp.pc_name,
        pc_profile_md=sp.pc_profile_md,
        pc_base_stats_json=sp.pc_base_stats_json,
        custom_prompt=sp.custom_prompt,
        outline_md=sp.outline_md,
        chapters_json=sp.chapters_json,
        main_characters_json=sp.main_characters_json,
        ending_md=sp.ending_md,
        opening_hook=sp.opening_hook,
        pc_tts_voice=sp.pc_tts_voice,
        version=sp.version,
        current_chapter=sp.current_chapter,
        completed_events_json=sp.completed_events_json,
        status=sp.status,
        created_at=sp.created_at.isoformat() if sp.created_at else "",
    )


@router.post("/worlds/{world_id}/screenplays", response_model=ScreenplayStandaloneOut, status_code=201)
async def create_world_screenplay(
    world_id: int,
    body: ScreenplayStandaloneIn,
    s: AsyncSession = Depends(get_session_dep),
):
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    sp = Screenplay(
        world_id=world_id,
        session_id=None,
        title=body.title,
        genre=body.genre,
        pc_name=body.pc_name,
        pc_profile_md=body.pc_profile_md,
        pc_base_stats_json=body.pc_base_stats_json,
        custom_prompt=body.custom_prompt,
        outline_md=body.outline_md,
        chapters_json=body.chapters_json,
        main_characters_json=body.main_characters_json,
        ending_md=body.ending_md,
        opening_hook=body.opening_hook,
        pc_tts_voice=body.pc_tts_voice,
    )
    s.add(sp)
    await s.commit()
    await s.refresh(sp)
    return _sp_to_out(sp)


@router.get("/worlds/{world_id}/screenplays", response_model=list[ScreenplayStandaloneOut])
async def list_world_screenplays(
    world_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    rows = (await s.execute(
        select(Screenplay)
        .where(Screenplay.world_id == world_id, Screenplay.session_id.is_(None))
        .order_by(Screenplay.created_at.desc())
    )).scalars().all()
    return [_sp_to_out(sp) for sp in rows]


@router.get("/screenplays", response_model=list[ScreenplayStandaloneOut])
async def list_all_screenplays(s: AsyncSession = Depends(get_session_dep)):
    """Cross-world list of standalone screenplays (those not attached to a
    specific session). Powers the global screenplay management view."""
    rows = (await s.execute(
        select(Screenplay)
        .where(Screenplay.session_id.is_(None))
        .order_by(Screenplay.created_at.desc())
    )).scalars().all()
    return [_sp_to_out(sp) for sp in rows]


@router.get("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def get_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    return _sp_to_out(sp)


@router.patch("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def patch_screenplay(
    screenplay_id: int,
    body: ScreenplayStandaloneIn,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sp, field, value)
    await s.commit()
    await s.refresh(sp)
    return _sp_to_out(sp)


@router.get("/screenplays/{screenplay_id}/refs")
async def screenplay_refs(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """How many sessions still reference this screenplay. Frontend uses this
    to decide whether to offer "also delete screenplay" after deleting a
    session."""
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    sess_count = len((
        await s.execute(
            select(SessionModel.id).where(SessionModel.screenplay_id == screenplay_id)
        )
    ).scalars().all())
    return {"sessions": sess_count}


@router.delete("/screenplays/{screenplay_id}", status_code=204)
async def delete_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    in_use = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.screenplay_id == screenplay_id).limit(1)
        )
    ).scalar_one_or_none()
    if in_use is not None:
        raise HTTPException(409, "screenplay is referenced by an existing session (剧本仍被存档使用)")
    await s.execute(
        sa_delete(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == screenplay_id)
    )
    await s.delete(sp)
    await s.commit()
