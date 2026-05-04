"""v0.2.0 wizard endpoints — POST /wizard/{world_brief, world_details,
character, npcs, screenplay, finalize}.

Each step is a single LLM call (timeout bumped to 600s for local 12B-class
models) except `finalize`, which is a pure DB transaction creating
World + Character + Session + pinned NPCs + Screenplay atomically.

The session dependency is reused from `routes_sessions` so the FastAPI
override applied in `main.py` covers this router automatically.
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
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
    generate_suggestions,
    generate_world_brief,
    generate_world_details,
    stream_character,
    stream_npcs,
    stream_screenplay,
    stream_world_brief,
    stream_world_details,
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


def _sse(gen):
    """Wrap an async generator of (event_type, data_dict) into EventSourceResponse."""
    async def _wrap() -> AsyncIterator[dict]:
        try:
            async for ev_type, data in gen:
                yield {"event": ev_type, "data": json.dumps(data, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
    return EventSourceResponse(_wrap())


@router.post("/world_brief/stream")
async def world_brief_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_world_brief(
        genre=str(payload.get("genre") or "悬疑探案"),
        theme=str(payload.get("theme") or ""),
        client=client,
    ))


@router.post("/world_details/stream")
async def world_details_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_world_details(
        brief_md=str(payload.get("brief_md") or ""),
        client=client,
    ))


@router.post("/character/stream")
async def character_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_character(
        world_md=str(payload.get("world_md") or ""),
        archetype=str(payload.get("archetype") or ""),
        client=client,
    ))


@router.post("/npcs/stream")
async def npcs_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_npcs(
        world_md=str(payload.get("world_md") or ""),
        character_md=str(payload.get("character_md") or ""),
        client=client,
    ))


@router.post("/screenplay/stream")
async def screenplay_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_screenplay(
        world_md=str(payload.get("world_md") or ""),
        character_md=str(payload.get("character_md") or ""),
        npcs=list(payload.get("npcs") or []),
        genre=str(payload.get("genre") or "悬疑探案"),
        client=client,
    ))


@router.post("/suggest")
async def suggest(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_suggestions(
            genre_hint=str(payload.get("genre") or ""),
            client=client,
        )
    except (ValueError, Exception) as e:
        raise HTTPException(502, f"suggestion generation failed: {e}") from e


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
