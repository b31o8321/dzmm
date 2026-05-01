"""v0.2.0 wizard endpoints — POST /wizard/{world_brief, world_details,
character, npcs, screenplay, finalize}.

Each step is a single LLM call (timeout bumped to 600s for local 12B-class
models) except `finalize`, which is a pure DB transaction creating
World + Character + Session + pinned NPCs + Screenplay atomically.

The session dependency is reused from `routes_sessions` so the FastAPI
override applied in `main.py` covers this router automatically.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions import get_session_dep
from dzmm.db.models import ModelConfig
from dzmm.models.factory import build_client
from dzmm.service.wizard import (
    finalize_wizard,
    generate_character,
    generate_npcs,
    generate_screenplay_from_wizard,
    generate_single_npc,
    generate_world_brief,
    generate_world_details,
)

router = APIRouter(prefix="/wizard", tags=["wizard"])

# Wizard LLM calls are single-shot multi-second generations; local models
# may need 1-3 minutes per step. Override cfg.timeout for the duration of
# the call (the cfg row in the DB is unchanged).
_WIZARD_TIMEOUT_SECONDS = 600.0


async def _client_for(s: AsyncSession, model_config_id: int):
    cfg = await s.get(ModelConfig, model_config_id)
    if cfg is None:
        raise HTTPException(404, "model_config not found")
    client = build_client(cfg)
    if hasattr(client, "timeout"):
        client.timeout = max(
            float(getattr(client, "timeout", 0.0) or 0.0),
            _WIZARD_TIMEOUT_SECONDS,
        )
    return client


def _require_int(payload: dict, key: str) -> int:
    if key not in payload:
        raise HTTPException(400, f"missing {key}")
    try:
        return int(payload[key])
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"{key} must be int") from e


@router.post("/world_brief")
async def world_brief(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_world_brief(
        genre=str(payload.get("genre") or "悬疑探案"),
        theme=str(payload.get("theme") or ""),
        client=client,
    )


@router.post("/world_details")
async def world_details(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_world_details(
        brief_md=str(payload.get("brief_md") or ""),
        client=client,
    )


@router.post("/character")
async def character(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_character(
        world_md=str(payload.get("world_md") or ""),
        archetype=str(payload.get("archetype") or ""),
        client=client,
    )


@router.post("/npcs")
async def npcs(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_npcs(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            client=client,
        )
    except ValueError as e:
        raise HTTPException(502, f"NPC generation parse failed: {e}") from e


@router.post("/screenplay")
async def screenplay(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_screenplay_from_wizard(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            npcs=list(payload.get("npcs") or []),
            genre=str(payload.get("genre") or "悬疑探案"),
            client=client,
        )
    except ValueError as e:
        raise HTTPException(502, f"screenplay generation parse failed: {e}") from e


@router.post("/npc/single")
async def npc_single(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_single_npc(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            hint=str(payload.get("hint") or ""),
            client=client,
        )
    except ValueError as e:
        raise HTTPException(502, f"NPC generation parse failed: {e}")


@router.post("/finalize")
async def finalize(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    try:
        session_id = await finalize_wizard(s, payload)
        await s.commit()
    except (KeyError, ValueError, TypeError) as e:
        await s.rollback()
        raise HTTPException(400, f"invalid bundle: {e}") from e
    return {"session_id": session_id}
