# backend/src/dzmm/api/routes_tts.py
"""TTS routes: proxy (existing), edge-tts builtin, kokoro-onnx local, cosyvoice sidecar."""
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
from dzmm.tts import cosyvoice_sidecar

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


class DirectTtsRequest(BaseModel):
    url: str = Field(..., max_length=500)  # base URL of the OpenAI-compatible TTS service
    text: str = Field(..., max_length=5000)
    voice: str = Field("default", max_length=120)
    model: str = Field("tts-1", max_length=120)


@router.post("/direct")
async def direct_tts(body: DirectTtsRequest):
    """Proxy synthesis to an arbitrary OpenAI-compatible TTS endpoint (LAN or localhost)."""
    if not body.text.strip():
        return Response(status_code=204)
    base = body.url.rstrip("/")
    endpoint = f"{base}/v1/audio/speech"
    payload = {"model": body.model, "input": body.text, "voice": body.voice}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"TTS server error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"TTS server unreachable: {e}")
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/mpeg"))


_VOICE_LABELS = {
    "zh-CN-XiaoxiaoNeural":          "晓晓（温柔/旁白）",
    "zh-CN-XiaoyiNeural":            "晓伊（活泼女）",
    "zh-CN-YunjianNeural":           "云健（叙事/导师）",
    "zh-CN-YunxiNeural":             "云希（盟友男）",
    "zh-CN-YunxiaNeural":            "云夏（青年男）",
    "zh-CN-YunyangNeural":           "云扬（商人/权威）",
    "zh-CN-liaoning-XiaobeiNeural":  "晓北（东北女）",
    "zh-CN-shaanxi-XiaoniNeural":    "晓妮（陕西女）",
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
    try:
        audio = await edge_synthesize(body.text, body.voice, rate=body.rate, pitch=body.pitch)
    except Exception as e:
        raise HTTPException(500, f"edge-tts synthesis failed: {e}")
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


# ---------------------------------------------------------------------------
# CosyVoice sidecar routes
# ---------------------------------------------------------------------------

import asyncio

# Background install task handle — prevent concurrent installs.
_cosy_install_task: asyncio.Task | None = None  # type: ignore[type-arg]
_cosy_install_log: list[str] = []
_cosy_install_error: str = ""


@router.get("/cosyvoice/status")
async def cosyvoice_status():
    installing = _cosy_install_task is not None and not _cosy_install_task.done()
    return {
        "installed": cosyvoice_sidecar.is_installed(),
        "running": cosyvoice_sidecar.is_running(),
        "port": cosyvoice_sidecar.port(),
        "installing": installing,
        "install_log": _cosy_install_log[-20:],
        "install_error": _cosy_install_error,
    }


@router.post("/cosyvoice/install")
async def cosyvoice_install():
    global _cosy_install_task, _cosy_install_log, _cosy_install_error
    if _cosy_install_task and not _cosy_install_task.done():
        return {"started": False, "detail": "install already in progress"}
    _cosy_install_log = []
    _cosy_install_error = ""

    def _on_progress(msg: str) -> None:
        _cosy_install_log.append(msg)

    async def _run() -> None:
        global _cosy_install_error
        try:
            await cosyvoice_sidecar.install(progress=_on_progress)
        except Exception as e:
            _cosy_install_error = str(e)

    _cosy_install_task = asyncio.create_task(_run())
    return {"started": True}


@router.post("/cosyvoice/start")
async def cosyvoice_start():
    if not cosyvoice_sidecar.is_installed():
        raise HTTPException(503, "CosyVoice not installed — run /tts/cosyvoice/install first")
    try:
        cosyvoice_sidecar.start()
    except Exception as e:
        raise HTTPException(500, f"start failed: {e}")
    return {"running": True, "port": cosyvoice_sidecar.port()}


@router.post("/cosyvoice/stop")
async def cosyvoice_stop():
    cosyvoice_sidecar.stop()
    return {"running": False}


class CosyVoiceProxyRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field("中文女", max_length=40)


@router.post("/cosyvoice/proxy")
async def cosyvoice_proxy(body: CosyVoiceProxyRequest):
    """Proxy synthesis request to the CosyVoice sidecar."""
    if not cosyvoice_sidecar.is_running():
        raise HTTPException(503, "CosyVoice sidecar not running — start it first")
    if not body.text.strip():
        return Response(status_code=204)
    url = f"http://127.0.0.1:{cosyvoice_sidecar.port()}/v1/audio/speech"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json={"input": body.text, "voice": body.voice})
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"sidecar error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"sidecar unreachable: {e}")
    if resp.status_code == 204:
        return Response(status_code=204)
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/wav"))
