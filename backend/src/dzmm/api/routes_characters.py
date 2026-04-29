from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import CharacterIn, CharacterOut
from dzmm.db.models import Character

router = APIRouter(prefix="/characters", tags=["characters"])


def get_session_dep():
    raise RuntimeError("override")


@router.post("", response_model=CharacterOut)
async def create_character(body: CharacterIn, s: AsyncSession = Depends(get_session_dep)):
    c = Character(**body.model_dump())
    s.add(c)
    await s.commit()
    await s.refresh(c)
    return CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                        profile_md=c.profile_md, base_stats_json=c.base_stats_json)


@router.get("", response_model=list[CharacterOut])
async def list_characters(world_id: int | None = None,
                          s: AsyncSession = Depends(get_session_dep)):
    q = select(Character).order_by(Character.id)
    if world_id is not None:
        q = q.where(Character.world_id == world_id)
    rows = (await s.execute(q)).scalars().all()
    return [
        CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                     profile_md=c.profile_md, base_stats_json=c.base_stats_json)
        for c in rows
    ]


@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, s: AsyncSession = Depends(get_session_dep)):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    return CharacterOut(id=c.id, world_id=c.world_id, name=c.name,
                        profile_md=c.profile_md, base_stats_json=c.base_stats_json)
