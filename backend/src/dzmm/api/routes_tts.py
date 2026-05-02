"""POST /tts — proxy to local OpenAI-compat TTS server."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import ModelConfig
from dzmm.secrets import get_api_key

router = APIRouter(prefix="/tts", tags=["tts"])


class TtsRequest(BaseModel):
    model_config_id: int
    text: str
    voice: str = "default"


@router.post("")
async def proxy_tts(body: TtsRequest, s: AsyncSession = Depends(get_session_dep)):
    cfg = await s.get(ModelConfig, body.model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")

    api_key = None
    if cfg.api_key_ref:
        api_key = get_api_key(cfg.api_key_ref)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": cfg.model_name,
        "input": body.text,
        "voice": body.voice,
    }

    base = cfg.base_url.rstrip("/")
    url = f"{base}/v1/audio/speech"

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"TTS server error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"TTS server unreachable: {e}")

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "audio/mpeg"),
    )
