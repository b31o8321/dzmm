# backend/src/dzmm/api/routes_tts.py
"""TTS routes: proxy (existing), edge-tts builtin, kokoro-onnx local."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import ModelConfig
from dzmm.secrets import get_api_key
from dzmm.tts.edge_engine import synthesize as edge_synthesize
from dzmm.tts.kokoro_engine import (
    is_model_ready as is_kokoro_ready,
    ensure_model as ensure_kokoro_model,
    synthesize as kokoro_synthesize,
)
from dzmm.tts.voice_map import EDGE_VOICES, NARRATOR_EDGE_VOICE

router = APIRouter(prefix="/tts", tags=["tts"])


class TtsRequest(BaseModel):
    model_config_id: int
    text: str = Field(..., max_length=5000)
    voice: str = Field("default", max_length=120)


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
    payload = {"model": cfg.model_name, "input": body.text, "voice": body.voice}
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
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/mpeg"))


_VOICE_LABELS = {
    "zh-CN-XiaoxiaoNeural":   "晓晓（温柔/旁白）",
    "zh-CN-XiaohanNeural":    "晓涵（活泼）",
    "zh-CN-XiaomoNeural":     "晓墨（冷静）",
    "zh-CN-XiaoqiuNeural":    "晓秋（沉稳/智者）",
    "zh-CN-XiaoshuangNeural": "晓双（儿童）",
    "zh-CN-XiaoxuanNeural":   "晓萱（成熟女）",
    "zh-CN-XiaozhenNeural":   "晓甄（平民）",
    "zh-CN-YunfengNeural":    "云枫（守卫/武将）",
    "zh-CN-YunhaoNeural":     "云皓（青年男）",
    "zh-CN-YunjianNeural":    "云健（叙事男）",
    "zh-CN-YunxiNeural":      "云希（盟友）",
    "zh-CN-YunyangNeural":    "云扬（商人/权威）",
    "zh-CN-YunyeNeural":      "云野（导师/反派）",
}


@router.get("/voices")
async def list_edge_voices():
    return [
        {"voice": v, "label": _VOICE_LABELS.get(v, v)}
        for v in sorted(set(EDGE_VOICES) | set(_VOICE_LABELS))
    ]


class BuiltinTtsRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field(NARRATOR_EDGE_VOICE, max_length=120)
    rate: str = Field("+0%", max_length=10)
    pitch: str = Field("+0Hz", max_length=10)


@router.post("/builtin")
async def builtin_tts(body: BuiltinTtsRequest):
    audio = await edge_synthesize(body.text, body.voice, rate=body.rate, pitch=body.pitch)
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/kokoro/status")
async def kokoro_status():
    return {"ready": is_kokoro_ready()}


@router.post("/kokoro/ensure")
async def kokoro_ensure():
    try:
        await ensure_kokoro_model()
    except Exception as e:
        raise HTTPException(500, f"kokoro download failed: {e}")
    return {"ready": True}


class KokoroSynthRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field("zf_xiaobei", max_length=60)
    speed: float = Field(1.0, ge=0.5, le=2.0)


@router.post("/kokoro/synthesize")
async def kokoro_synth(body: KokoroSynthRequest):
    if not is_kokoro_ready():
        raise HTTPException(503, "kokoro model not downloaded")
    try:
        audio = await kokoro_synthesize(body.text, body.voice, body.speed)
    except Exception as e:
        raise HTTPException(500, f"kokoro synthesis failed: {e}")
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")
