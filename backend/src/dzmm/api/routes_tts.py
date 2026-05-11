# ============================================================
# routes_tts.py — TTS（文字转语音）API 路由
# ============================================================
#
# 【什么是 TTS？】
#   TTS = Text-to-Speech（文字转语音）。
#   把文字内容合成为语音音频，让 NPC 和旁白能"开口说话"，
#   增强跑团的沉浸感，听到 NPC 的声音比只看文字更有代入感。
#
# 【为什么有多种 TTS 引擎？】
#   不同引擎各有取舍：
#   1. proxy（代理模式）  — 转发到用户配置的远程 TTS 服务（如云端 OpenAI TTS），
#                          需要 API Key，音质好，但要联网且收费。
#   2. direct（直连模式） — 转发到用户自填的任意 URL（如局域网里的私有 TTS 服务）。
#   3. builtin/edge-tts   — 使用微软 Edge 的神经网络 TTS，免费，无需 API Key，
#                          纯 Python 包，开箱即用。
#   4. kokoro-onnx        — 完全本地运行的开源 TTS 模型，需要下载模型文件，
#                          离线可用，无需网络。
#   5. CosyVoice 侧车     — 阿里巴巴的高质量中文 TTS，需要单独安装，
#                          作为"侧车进程"独立运行（见下方说明）。
#
# 【什么是"侧车进程"（sidecar）？】
#   侧车（sidecar）是一种架构模式：主进程（这里是 FastAPI 后端）负责业务逻辑，
#   而某些耗资源或有特殊依赖的功能（比如 CosyVoice 需要 PyTorch + 大模型），
#   拆分成独立的子进程单独运行，主进程通过 HTTP 与它通信。
#   好处：侧车崩溃不影响主进程；可以按需启动/停止，节省内存；
#         可以用不同的 Python 环境（避免依赖冲突）。
#   CosyVoice 侧车在本机 127.0.0.1 的某个端口运行，后端向它发 HTTP 请求。
#
# 【文件结构】
#   - TtsRequest + proxy_tts:      通过数据库里的 ModelConfig 配置转发 TTS 请求
#   - DirectTtsRequest + direct_tts: 直接转发到任意 URL 的 TTS 服务
#   - probe_tts:                   探测某个 TTS 服务是否可达
#   - list_edge_voices:            列出可用的 Edge TTS 声音
#   - BuiltinTtsRequest + builtin_tts: 使用内置 edge-tts 引擎合成
#   - kokoro_status/ensure/synth:  kokoro-onnx 本地引擎的管理接口
#   - cosyvoice_*:                 CosyVoice 侧车的安装/启动/停止/合成接口

# backend/src/dzmm/api/routes_tts.py
"""TTS routes: proxy (existing), edge-tts builtin, kokoro-onnx local, cosyvoice sidecar."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response   # Response — 返回原始字节内容（音频数据）
from pydantic import BaseModel, Field    # BaseModel — Pydantic 数据校验基类；Field — 字段配置
from sqlalchemy.ext.asyncio import AsyncSession
import httpx   # httpx — 异步 HTTP 客户端，用于向外部 TTS 服务发请求

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import ModelConfig
from dzmm.secrets import get_api_key    # 从安全存储中读取 API Key（不明文存数据库）

# edge-tts 引擎：调用微软神经网络 TTS API（免费，需要联网）
from dzmm.tts.edge_engine import synthesize as edge_synthesize

# kokoro-onnx 本地引擎：完全离线运行，需要先下载模型文件
from dzmm.tts.kokoro_engine import (
    is_model_ready as is_kokoro_ready,       # 检查模型文件是否已下载完毕
    ensure_model as ensure_kokoro_model,     # 下载模型（如未下载）
    synthesize as kokoro_synthesize,         # 合成语音
)

# EDGE_VOICES — edge-tts 支持的所有声音 ID 列表
# NARRATOR_EDGE_VOICE — 默认旁白声音 ID
from dzmm.tts.voice_map import EDGE_VOICES, NARRATOR_EDGE_VOICE

# cosyvoice_sidecar — CosyVoice 侧车进程管理模块
# 提供 is_installed / is_running / install / start / stop / port 等函数
from dzmm.tts import cosyvoice_sidecar

# 所有 TTS 接口统一挂载在 /tts 路径下
router = APIRouter(prefix="/tts", tags=["tts"])


# ──────────────────────────────────────────────
# 1. 代理模式 TTS（通过 ModelConfig 配置转发）
# ──────────────────────────────────────────────

# Pydantic 请求体模型：定义前端可以发来哪些字段，以及它们的类型和限制
class TtsRequest(BaseModel):
    model_config_id: int                         # 指向数据库里 ModelConfig 记录的 id
    text: str = Field(..., max_length=5000)      # 要合成的文本，最多 5000 字
    voice: str = Field("default", max_length=120)  # 声音 ID，默认 "default"


# POST /tts
# 代理 TTS：根据 model_config_id 从数据库读取 TTS 服务配置，向它发请求并把音频返回给前端
@router.post("")
async def proxy_tts(body: TtsRequest, s: AsyncSession = Depends(get_session_dep)):
    # 从数据库查出 TTS 服务的配置（包含 base_url、model_name、api_key_ref 等）
    cfg = await s.get(ModelConfig, body.model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")
    # api_key_ref 是密钥的"引用名"（不是明文），从安全存储里取出实际密钥
    api_key = None
    if cfg.api_key_ref:
        api_key = get_api_key(cfg.api_key_ref)
    # 构建 HTTP 请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"  # Bearer Token 认证
    # OpenAI TTS API 格式的请求体
    payload = {"model": cfg.model_name, "input": body.text, "voice": body.voice}
    # 拼接完整的 TTS 端点 URL（OpenAI 兼容格式：/v1/audio/speech）
    base = cfg.base_url.rstrip("/")  # 去掉末尾的 /，防止拼接后出现双斜杠
    url = f"{base}/v1/audio/speech"
    try:
        # 异步 HTTP 客户端，with 语句保证请求结束后自动关闭连接
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()  # 4xx/5xx 状态码会抛出异常
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"TTS server error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(503, f"TTS server unreachable: {e}")  # 503 = 服务不可用
    # 把音频字节流直接返回，media_type 从响应头取（通常是 audio/mpeg 或 audio/wav）
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/mpeg"))


# ──────────────────────────────────────────────
# 2. 直连模式 TTS（直接转发到任意 URL）
# ──────────────────────────────────────────────

class DirectTtsRequest(BaseModel):
    url: str = Field(..., max_length=500)   # 目标 TTS 服务的 base URL（用户手填）
    text: str = Field(..., max_length=5000)
    voice: str = Field("default", max_length=120)
    model: str = Field("tts-1", max_length=120)  # TTS 模型名，默认 "tts-1"


# GET /tts/probe
# 探测一个 TTS 服务是否可达（依次尝试 /health、/v1/models、/ 路径）
# 用于前端"测试连接"按钮
@router.get("/probe")
async def probe_tts(url: str):
    """Check if an external TTS service is reachable (tries /health then /v1/models)."""
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=5) as client:  # 探测超时设 5 秒，不要等太久
        for path in ("/health", "/v1/models", "/"):
            try:
                r = await client.get(f"{base}{path}")
                # 只要能收到响应（不管状态码），就认为服务可达
                return {"ok": True, "status": r.status_code, "url": f"{base}{path}"}
            except httpx.RequestError:
                continue  # 连接失败，尝试下一个路径
    return {"ok": False, "status": None, "url": base}


# POST /tts/direct
# 直连转发：把请求直接转发到用户指定的任意 OpenAI 兼容 TTS 服务
# 用于局域网部署场景（比如用户在家里的另一台电脑上跑 TTS 服务）
@router.post("/direct")
async def direct_tts(body: DirectTtsRequest):
    """Proxy synthesis to an arbitrary OpenAI-compatible TTS endpoint (LAN or localhost)."""
    if not body.text.strip():
        return Response(status_code=204)  # 空文本，返回 204 No Content（不报错）
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


# ──────────────────────────────────────────────
# 3. 内置 Edge TTS（微软神经网络 TTS，免费）
# ──────────────────────────────────────────────

# 声音 ID 到中文标签的映射，方便前端显示友好名称
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


# GET /tts/voices
# 列出所有可用的 Edge TTS 声音（合并配置文件里的声音列表和标签字典里的声音）
@router.get("/voices")
async def list_edge_voices():
    # sorted(set(A) | set(B)) — 两个集合取并集再排序，去重且按字母顺序
    return [
        {"voice": v, "label": _VOICE_LABELS.get(v, v)}  # 没有标签的就直接用 ID 作标签
        for v in sorted(set(EDGE_VOICES) | set(_VOICE_LABELS))
    ]


class BuiltinTtsRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field(NARRATOR_EDGE_VOICE, max_length=120)  # 默认旁白声音
    rate: str = Field("+0%", max_length=10)     # 语速调整，如 "+20%" 加快 20%
    pitch: str = Field("+0Hz", max_length=10)   # 音调调整，如 "+50Hz" 提高音调


# POST /tts/builtin
# 使用内置 edge-tts 引擎合成语音，返回 MP3 音频字节流
@router.post("/builtin")
async def builtin_tts(body: BuiltinTtsRequest):
    try:
        audio = await edge_synthesize(body.text, body.voice, rate=body.rate, pitch=body.pitch)
    except Exception as e:
        raise HTTPException(500, f"edge-tts synthesis failed: {e}")
    if not audio:
        return Response(status_code=204)  # 合成结果为空（比如输入是空格），返回 204
    return Response(content=audio, media_type="audio/mpeg")


# ──────────────────────────────────────────────
# 4. Kokoro-ONNX 本地 TTS（完全离线）
# ──────────────────────────────────────────────

# GET /tts/kokoro/status
# 检查 kokoro 模型文件是否已下载完毕，前端据此决定是否显示"下载模型"按钮
@router.get("/kokoro/status")
async def kokoro_status():
    return {"ready": is_kokoro_ready()}


# POST /tts/kokoro/ensure
# 触发 kokoro 模型下载（如果已下载则跳过）
@router.post("/kokoro/ensure")
async def kokoro_ensure():
    try:
        await ensure_kokoro_model()
    except Exception as e:
        raise HTTPException(500, f"kokoro download failed: {e}")
    return {"ready": True}


class KokoroSynthRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field("zf_xiaobei", max_length=60)  # kokoro 声音 ID，默认中文女声"小贝"
    speed: float = Field(1.0, ge=0.5, le=2.0)  # 语速，0.5（最慢）到 2.0（最快）


# POST /tts/kokoro/synthesize
# 使用本地 kokoro-onnx 引擎合成语音，返回 WAV 格式音频
@router.post("/kokoro/synthesize")
async def kokoro_synth(body: KokoroSynthRequest):
    if not is_kokoro_ready():
        raise HTTPException(503, "kokoro model not downloaded")  # 503 = 服务未就绪
    try:
        audio = await kokoro_synthesize(body.text, body.voice, body.speed)
    except Exception as e:
        raise HTTPException(500, f"kokoro synthesis failed: {e}")
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")  # kokoro 输出 WAV 格式


# ──────────────────────────────────────────────
# 5. CosyVoice 侧车进程管理
# ──────────────────────────────────────────────
# CosyVoice 是阿里巴巴开源的高质量中文 TTS 模型。
# 它依赖 PyTorch 等重量级包，如果直接集成到 FastAPI 进程里会大幅增加启动时间和内存。
# 所以把它作为"侧车"——独立的子进程，监听本机某个端口，
# FastAPI 通过 HTTP 向它转发请求。

import asyncio

# 全局状态变量：追踪安装任务的进度
# asyncio.Task 是异步任务对象；None 表示当前没有安装任务在运行
_cosy_install_task: asyncio.Task | None = None  # type: ignore[type-arg]
_cosy_install_log: list[str] = []   # 安装过程的日志行列表，供前端实时轮询显示
_cosy_install_error: str = ""       # 安装失败时记录错误信息


# GET /tts/cosyvoice/status
# 返回 CosyVoice 侧车的完整状态：是否已安装、是否正在运行、端口号、安装日志等
@router.get("/cosyvoice/status")
async def cosyvoice_status():
    # 判断安装任务是否正在进行中（任务存在且未完成）
    installing = _cosy_install_task is not None and not _cosy_install_task.done()
    return {
        "installed": cosyvoice_sidecar.is_installed(),  # 模型和依赖是否安装完毕
        "running": cosyvoice_sidecar.is_running(),      # 侧车进程是否正在运行
        "port": cosyvoice_sidecar.port(),               # 侧车监听的端口号
        "installing": installing,                        # 是否正在安装中
        "install_log": _cosy_install_log[-20:],         # 只返回最后 20 条日志，避免响应太大
        "install_error": _cosy_install_error,
    }


# POST /tts/cosyvoice/install
# 触发 CosyVoice 安装（异步后台任务），立即返回不等待安装完成。
# 前端可以通过轮询 /tts/cosyvoice/status 查看安装进度。
@router.post("/cosyvoice/install")
async def cosyvoice_install():
    global _cosy_install_task, _cosy_install_log, _cosy_install_error
    # 防止并发安装：如果已有安装任务在运行，直接返回提示
    if _cosy_install_task and not _cosy_install_task.done():
        return {"started": False, "detail": "install already in progress"}
    # 重置日志和错误信息，开始新一轮安装
    _cosy_install_log = []
    _cosy_install_error = ""

    # 进度回调函数：每当安装步骤有新进展，就把消息追加到日志列表
    def _on_progress(msg: str) -> None:
        _cosy_install_log.append(msg)

    # 实际安装的异步函数，在后台运行
    async def _run() -> None:
        global _cosy_install_error
        try:
            await cosyvoice_sidecar.install(progress=_on_progress)
        except Exception as e:
            _cosy_install_error = str(e)  # 安装失败，记录错误

    # asyncio.create_task 把协程包装成任务，立即在后台开始执行，不阻塞当前请求
    _cosy_install_task = asyncio.create_task(_run())
    return {"started": True}


# POST /tts/cosyvoice/start
# 启动 CosyVoice 侧车进程（必须先安装才能启动）
@router.post("/cosyvoice/start")
async def cosyvoice_start():
    if not cosyvoice_sidecar.is_installed():
        raise HTTPException(503, "CosyVoice not installed — run /tts/cosyvoice/install first")
    try:
        cosyvoice_sidecar.start()  # 启动侧车子进程
    except Exception as e:
        raise HTTPException(500, f"start failed: {e}")
    return {"running": True, "port": cosyvoice_sidecar.port()}


# POST /tts/cosyvoice/stop
# 停止 CosyVoice 侧车进程（释放内存和端口）
@router.post("/cosyvoice/stop")
async def cosyvoice_stop():
    cosyvoice_sidecar.stop()
    return {"running": False}


class CosyVoiceProxyRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    voice: str = Field("中文女", max_length=40)  # CosyVoice 支持的声音名称


# POST /tts/cosyvoice/proxy
# 把合成请求转发给正在运行的 CosyVoice 侧车，并把音频返回给前端
@router.post("/cosyvoice/proxy")
async def cosyvoice_proxy(body: CosyVoiceProxyRequest):
    """Proxy synthesis request to the CosyVoice sidecar."""
    if not cosyvoice_sidecar.is_running():
        raise HTTPException(503, "CosyVoice sidecar not running — start it first")
    if not body.text.strip():
        return Response(status_code=204)
    # 侧车监听在本机（127.0.0.1）的某个端口，使用 OpenAI 兼容的 API 格式
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
    # 直接把侧车返回的音频字节流原样转发给前端
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/wav"))
