"""Sessions CRUD: POST/GET/DELETE /sessions, /sessions/{id}.

DELETE cascades through every per-session table since SQLite FKs aren't
enabled on this schema."""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import (
    _to_out,
    delete_session_cascade,
    get_session_dep,
)
from dzmm.api.schemas import SessionIn, SessionOut
from dzmm.db.models import (
    CharState,
    ModelConfig,
    NPC,
    Screenplay,
    Session as GameSession,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


class PatchGmModelRequest(BaseModel):
    gm_model_config_id: int


class PatchSettingsRequest(BaseModel):
    narrative_polish: bool | None = None
    debug_mode: bool | None = None
    content_level: str | None = None  # safe | mature | unrestricted
    use_v10: bool | None = None


@router.patch("/{session_id}/settings")
async def patch_session_settings(
    session_id: int,
    body: PatchSettingsRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    settings = json.loads(sess.settings_json or "{}")
    if body.narrative_polish is not None:
        settings["narrative_polish"] = body.narrative_polish
    if body.debug_mode is not None:
        settings["debug_mode"] = body.debug_mode
    if body.content_level in ("safe", "mature", "unrestricted"):
        settings["content_level"] = body.content_level
    if body.use_v10 is not None:
        settings["use_v10"] = body.use_v10
    sess.settings_json = json.dumps(settings)
    await s.commit()
    return {"id": sess.id, "settings": settings}


@router.get("/{session_id}/settings")
async def get_session_settings(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return {"id": sess.id, "settings": json.loads(sess.settings_json or "{}")}


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


class PatchDebugStateRequest(BaseModel):
    doom_score: int | None = None
    turn_count: int | None = None
    scene_turn_count: int | None = None
    stats_json: str | None = None
    inventory_json: str | None = None


@router.patch("/{session_id}/debug_state", status_code=200)
async def patch_debug_state(
    session_id: int,
    body: PatchDebugStateRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    if body.doom_score is not None:
        sess.doom_score = max(0, min(100, body.doom_score))
    if body.turn_count is not None:
        sess.turn_count = max(0, body.turn_count)
    if body.scene_turn_count is not None:
        sess.scene_turn_count = max(0, body.scene_turn_count)

    if body.stats_json is not None or body.inventory_json is not None:
        cs = (
            await s.execute(select(CharState).where(CharState.session_id == session_id))
        ).scalar_one_or_none()
        if cs is None:
            cs = CharState(session_id=session_id)
            s.add(cs)
        if body.stats_json is not None:
            json.loads(body.stats_json)  # validate JSON
            cs.stats_json = body.stats_json
        if body.inventory_json is not None:
            json.loads(body.inventory_json)  # validate JSON
            cs.inventory_json = body.inventory_json

    await s.commit()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
    }


@router.get("/{session_id}/debug_state")
async def get_debug_state(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cs = (
        await s.execute(select(CharState).where(CharState.session_id == session_id))
    ).scalar_one_or_none()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
        "settings": json.loads(sess.settings_json or "{}"),
        "stats": json.loads(cs.stats_json if cs else "{}"),
        "inventory": json.loads(cs.inventory_json if cs else "[]"),
    }


@router.post("", response_model=SessionOut)
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    from dzmm.db.models import Character as CharacterRow

    world_id = body.world_id
    character_id = body.character_id

    if body.screenplay_id is not None:
        sp = await s.get(Screenplay, body.screenplay_id)
        if sp is None:
            raise HTTPException(404, "screenplay not found")
        world_id = sp.world_id
        char = CharacterRow(
            world_id=world_id,
            name=sp.pc_name or "主角",
            gender=sp.pc_gender or "",
            profile_md=sp.pc_profile_md or "",
            base_stats_json=sp.pc_base_stats_json or "{}",
        )
        s.add(char)
        await s.flush()
        character_id = char.id
    elif world_id is None or character_id is None:
        raise HTTPException(422, "either screenplay_id or both world_id+character_id are required")

    sess = GameSession(
        name=body.name,
        world_id=world_id,
        character_id=character_id,
        screenplay_id=body.screenplay_id,
        gm_model_config_id=body.gm_model_config_id,
        summarizer_model_config_id=body.summarizer_model_config_id,
    )
    s.add(sess)
    await s.flush()
    # v0.10.4: copy Character.base_stats_json → CharState.stats_json so the
    # StatePanel shows the wizard-defined HP/sanity/etc from turn 0 instead
    # of '尚未初始化'. Backwards-compat: if Character row is missing or has
    # malformed JSON, CharState falls back to default '{}'.
    from dzmm.db.models import Character as _CharacterModel
    _initial_stats = "{}"
    if character_id is not None:
        _ch = await s.get(_CharacterModel, character_id)
        if _ch is not None and _ch.base_stats_json:
            _initial_stats = _ch.base_stats_json
    s.add(CharState(session_id=sess.id, stats_json=_initial_stats))

    # Tier-1 复用现有剧本：把剧本绑回新存档，并重置进度字段，让 GM/前端的
    # get_active_screenplay 能在新会话里找到它，且从第 1 章开始重玩。
    if body.screenplay_id is not None:
        sp = await s.get(Screenplay, body.screenplay_id)
        if sp is not None:
            sp.session_id = sess.id
            sp.current_chapter = 1
            sp.completed_events_json = "[]"
            sp.status = "active"

            # Import NPC templates from screenplay into new session.
            # Lets preset screenplays start with a populated NPC list.
            try:
                npc_templates = json.loads(sp.npcs_json or "[]")
            except (ValueError, TypeError):
                npc_templates = []
            for tpl in npc_templates:
                if not isinstance(tpl, dict) or not tpl.get("name"):
                    continue
                s.add(NPC(
                    session_id=sess.id,
                    name=tpl.get("name", ""),
                    gender=tpl.get("gender", ""),
                    archetype=tpl.get("archetype", ""),
                    description=tpl.get("description", ""),
                    state=tpl.get("state", "未知"),
                    purpose=tpl.get("purpose", ""),
                    favor=0,
                    pinned=True,
                    last_seen_turn=0,
                    notes_json="[]",
                    affinity_json="{}",
                    revealed_json='{"name": true}',
                ))

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
    """Delete a session and all of its associated rows. The world, character,
    and model_configs are NOT touched (shared across sessions)."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    await delete_session_cascade(s, session_id)
    await s.delete(sess)
    await s.commit()
    return
