import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import WorldIn, WorldOut
from dzmm.db.models import World

router = APIRouter(prefix="/worlds", tags=["worlds"])


def _to_out(w: World) -> WorldOut:
    rules = json.loads(w.rules_json or '{"mode":"light"}')
    return WorldOut(id=w.id, name=w.name, content_md=w.content_md,
                    style=w.style, rules_mode=rules.get("mode", "light"))


def get_session_dep():
    raise RuntimeError("override via dependency_overrides")


@router.post("", response_model=WorldOut)
async def create_world(body: WorldIn, s: AsyncSession = Depends(get_session_dep)):
    w = World(
        name=body.name,
        content_md=body.content_md,
        style=body.style,
        rules_json=json.dumps({"mode": body.rules_mode}),
    )
    s.add(w)
    await s.commit()
    await s.refresh(w)
    return _to_out(w)


@router.get("", response_model=list[WorldOut])
async def list_worlds(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(select(World).order_by(World.id))).scalars().all()
    return [_to_out(w) for w in rows]


@router.get("/{world_id}", response_model=WorldOut)
async def get_world(world_id: int, s: AsyncSession = Depends(get_session_dep)):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    return _to_out(w)
