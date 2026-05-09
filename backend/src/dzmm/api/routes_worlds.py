import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import delete_session_cascade
from dzmm.api.schemas import WorldIn, WorldOut
from dzmm.db.models import Character as CharacterModel
from dzmm.db.models import ModelConfig
from dzmm.db.models import Screenplay
from dzmm.db.models import Session as SessionModel
from dzmm.db.models import World
from dzmm.service.world_rag import index_world_async

router = APIRouter(prefix="/worlds", tags=["worlds"])


def _to_out(w: World) -> WorldOut:
    rules = json.loads(w.rules_json or '{"mode":"light"}')
    return WorldOut(id=w.id, name=w.name, content_md=w.content_md,
                    style=w.style, rules_mode=rules.get("mode", "light"))


class ReindexRequest(BaseModel):
    ollama_url: str
    model: str = "nomic-embed-text"


def get_session_dep():
    raise RuntimeError("override via dependency_overrides")


async def _maybe_trigger_reindex(w: World, s: AsyncSession) -> None:
    """Fire-and-forget RAG reindex after world create/update.

    Looks up the first available ModelConfig for its base_url.
    Silently skips if no config exists or content is empty.
    """
    if not w.content_md:
        return
    cfg = (await s.execute(select(ModelConfig).limit(1))).scalar_one_or_none()
    if cfg is None:
        return
    try:
        asyncio.create_task(
            index_world_async(w.id, w.content_md, cfg.base_url)
        )
    except RuntimeError:
        # No running event loop in tests — skip silently
        pass


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
    await _maybe_trigger_reindex(w, s)
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


@router.put("/{world_id}", response_model=WorldOut)
async def update_world(
    world_id: int, body: WorldIn, s: AsyncSession = Depends(get_session_dep)
):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    w.name = body.name
    w.content_md = body.content_md
    w.style = body.style
    w.rules_json = json.dumps({"mode": body.rules_mode})
    await s.commit()
    await s.refresh(w)
    await _maybe_trigger_reindex(w, s)
    return _to_out(w)


@router.get("/{world_id}/cascade_summary")
async def cascade_summary(world_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return counts of subresources that would be deleted with cascade=true.
    Used by the frontend to show a confirmation dialog before destructive delete."""
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    chars = len((
        await s.execute(select(CharacterModel.id).where(CharacterModel.world_id == world_id))
    ).scalars().all())
    sessions = len((
        await s.execute(select(SessionModel.id).where(SessionModel.world_id == world_id))
    ).scalars().all())
    screenplays = len((
        await s.execute(
            select(Screenplay.id).where(
                Screenplay.world_id == world_id, Screenplay.session_id.is_(None),
            )
        )
    ).scalars().all())
    return {"characters": chars, "sessions": sessions, "screenplays": screenplays}


@router.delete("/{world_id}", status_code=204)
async def delete_world(
    world_id: int,
    cascade: bool = Query(False, description="If true, also delete this world's characters, screenplays, and sessions (with all per-session subresources)."),
    s: AsyncSession = Depends(get_session_dep),
):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")

    if not cascade:
        has_chars = (
            await s.execute(
                select(CharacterModel.id).where(CharacterModel.world_id == world_id).limit(1)
            )
        ).scalar_one_or_none()
        if has_chars is not None:
            raise HTTPException(409, "world has characters (该世界仍有角色)")
        has_sessions = (
            await s.execute(
                select(SessionModel.id).where(SessionModel.world_id == world_id).limit(1)
            )
        ).scalar_one_or_none()
        if has_sessions is not None:
            raise HTTPException(409, "world has sessions (该世界仍有跑团存档)")
        await s.delete(w)
        await s.commit()
        return

    # Cascade path. Delete order:
    # 1) sessions (each via delete_session_cascade — also wipes any
    #    session-scoped Screenplay rows where session_id IS NOT NULL).
    # 2) world-level Screenplays (session_id IS NULL, world_id = this).
    # 3) characters of this world.
    # 4) the world row itself.
    sess_ids = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.world_id == world_id)
        )
    ).scalars().all()
    for sid in sess_ids:
        await delete_session_cascade(s, sid)
    if sess_ids:
        await s.execute(
            sa_delete(SessionModel).where(SessionModel.id.in_(sess_ids))
        )
    await s.execute(
        sa_delete(Screenplay).where(
            Screenplay.world_id == world_id, Screenplay.session_id.is_(None),
        )
    )
    await s.execute(
        sa_delete(CharacterModel).where(CharacterModel.world_id == world_id)
    )
    await s.delete(w)
    await s.commit()

    # Drop the world's vector index so embeddings on disk don't outlive the
    # World row. Best-effort; swallow errors so a stale ChromaDB never
    # blocks the user's "clean up this world" flow.
    from dzmm.service.world_rag import delete_world_index
    delete_world_index(world_id)


@router.post("/{world_id}/reindex", status_code=202)
async def reindex_world(
    world_id: int,
    body: ReindexRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    """手动触发世界书重新索引（向量化存入 ChromaDB）。

    返回 202 Accepted：后台异步执行，不等待完成。
    """
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    if not w.content_md:
        return {"status": "skipped", "reason": "empty content"}
    asyncio.create_task(
        index_world_async(w.id, w.content_md, body.ollama_url, body.model)
    )
    return {"status": "started"}
