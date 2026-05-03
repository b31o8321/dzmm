# TTS Engines Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new built-in TTS modes — edge-tts (online, free, 16 Chinese Neural voices) and kokoro-onnx (offline, ~82MB ONNX model, no PyTorch) — with NPC archetype → voice auto-assignment and a download progress UI for the kokoro model.

**Architecture:** edge-tts calls Microsoft's free Neural TTS service; kokoro-onnx runs the hexgrad/Kokoro-82M ONNX model in-process (no subprocess, no sidecar). Both are exposed via new `/tts/builtin` and `/tts/kokoro` endpoints alongside the existing `/tts` proxy. CosyVoice is out of scope — it requires PyTorch (~2 GB deps on top of the 300 MB model), making it unsuitable for desktop bundling; users who want CosyVoice can configure it via the existing proxy mode. NPC archetype field drives auto-voice selection so new NPCs don't need manual configuration.

**Tech Stack:** `edge-tts` (pip), `kokoro-onnx` (pip), `soundfile` (pip), `huggingface_hub` (already pulled in by chromadb), Web Audio API (existing frontend), Vue 3 + Element Plus (existing frontend)

---

## File Structure

**New backend files:**
- `backend/src/dzmm/tts/__init__.py` — empty package marker
- `backend/src/dzmm/tts/voice_map.py` — archetype → voice/prosody mapping for both engines
- `backend/src/dzmm/tts/edge_engine.py` — edge-tts synthesis
- `backend/src/dzmm/tts/kokoro_engine.py` — kokoro-onnx download check + synthesis

**Modified backend files:**
- `backend/src/dzmm/api/routes_tts.py` — add 5 new endpoints
- `backend/pyproject.toml` — add edge-tts, kokoro-onnx, soundfile
- `backend/dzmm-backend.spec` — add hidden imports for new deps

**New backend test:**
- `backend/tests/test_tts_engines.py`

**Modified frontend files:**
- `frontend/src/stores/app.ts` — extend `ttsMode` type to include `'edge'` and `'kokoro'`
- `frontend/src/composables/useTTS.ts` — add edge + kokoro synthesize paths
- `frontend/src/components/TtsSettingsCard.vue` — 4-mode radio, kokoro install UI
- `frontend/src/components/NpcDetailDialog.vue` — archetype-based voice preset dropdown

---

### Task 1: Voice mapping module

**Files:**
- Create: `backend/src/dzmm/tts/__init__.py`
- Create: `backend/src/dzmm/tts/voice_map.py`
- Create: `backend/tests/test_tts_engines.py` (partial — voice map tests only)

- [ ] **Step 1: Create the tts package**

```python
# backend/src/dzmm/tts/__init__.py
# (empty)
```

- [ ] **Step 2: Write failing tests for voice_map**

```python
# backend/tests/test_tts_engines.py
import pytest
from dzmm.tts.voice_map import (
    edge_voice_for_archetype,
    edge_prosody_for_archetype,
    kokoro_voice_for_archetype,
    EDGE_VOICES,
    NARRATOR_EDGE_VOICE,
    NARRATOR_KOKORO_VOICE,
)


def test_edge_known_archetypes():
    assert edge_voice_for_archetype("冷酷") == "zh-CN-XiaomoNeural"
    assert edge_voice_for_archetype("温柔") == "zh-CN-XiaoxiaoNeural"
    assert edge_voice_for_archetype("活泼") == "zh-CN-XiaohanNeural"
    assert edge_voice_for_archetype("反派") == "zh-CN-YunyeNeural"
    assert edge_voice_for_archetype("导师") == "zh-CN-YunyeNeural"


def test_edge_unknown_archetype_returns_default():
    v = edge_voice_for_archetype("未知类型")
    assert v in EDGE_VOICES


def test_edge_prosody_returns_tuple():
    rate, pitch = edge_prosody_for_archetype("冷酷")
    assert rate.endswith("%")
    assert pitch.endswith("Hz")


def test_kokoro_known_archetypes():
    assert kokoro_voice_for_archetype("温柔") == "zf_xiaobei"
    assert kokoro_voice_for_archetype("活泼") == "zf_xiaoni"
    assert kokoro_voice_for_archetype("导师") == "zm_yunxi"
    assert kokoro_voice_for_archetype("反派") == "zm_yundong"


def test_kokoro_unknown_archetype_returns_default():
    v = kokoro_voice_for_archetype("未知")
    assert v in ("zf_xiaobei", "zf_xiaoni", "zm_yunxi", "zm_yundong")


def test_narrator_voices_defined():
    assert NARRATOR_EDGE_VOICE.startswith("zh-CN-")
    assert NARRATOR_KOKORO_VOICE.startswith("z")
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -v 2>&1 | head -30
```

Expected: FAIL — `ModuleNotFoundError: No module named 'dzmm.tts'`

- [ ] **Step 4: Implement voice_map.py**

```python
# backend/src/dzmm/tts/voice_map.py
"""Archetype → TTS voice/prosody mappings for edge-tts and kokoro-onnx."""

# edge-tts: archetype → (voice_name, rate_adjust, pitch_adjust_hz)
_EDGE_MAP: dict[str, tuple[str, str, str]] = {
    "导师":  ("zh-CN-YunyeNeural",    "-5%",  "-2Hz"),
    "盟友":  ("zh-CN-YunxiNeural",    "+0%",  "+0Hz"),
    "反派":  ("zh-CN-YunyeNeural",    "+5%",  "-5Hz"),
    "神秘人":("zh-CN-XiaoqiuNeural",  "-15%", "-3Hz"),
    "商人":  ("zh-CN-YunyangNeural",  "+8%",  "+0Hz"),
    "守卫":  ("zh-CN-YunfengNeural",  "+0%",  "-1Hz"),
    "平民":  ("zh-CN-XiaozhenNeural", "+0%",  "+0Hz"),
    "智者":  ("zh-CN-XiaoqiuNeural",  "-20%", "-4Hz"),
    "冷酷":  ("zh-CN-XiaomoNeural",   "-10%", "-3Hz"),
    "温柔":  ("zh-CN-XiaoxiaoNeural", "-5%",  "+2Hz"),
    "活泼":  ("zh-CN-XiaohanNeural",  "+15%", "+3Hz"),
    "邪恶":  ("zh-CN-YunyeNeural",    "+0%",  "-6Hz"),
    "儿童":  ("zh-CN-XiaoshuangNeural","+15%","+5Hz"),
    "长老":  ("zh-CN-XiaoqiuNeural",  "-20%", "-5Hz"),
    "武将":  ("zh-CN-YunfengNeural",  "+5%",  "-2Hz"),
    "贵族":  ("zh-CN-YunyangNeural",  "-5%",  "+0Hz"),
}

_EDGE_DEFAULT = ("zh-CN-YunxiNeural", "+0%", "+0Hz")
NARRATOR_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"  # audiobook-style narrator

# All distinct edge voice names (for validation/listing)
EDGE_VOICES: list[str] = sorted({v for v, _, _ in _EDGE_MAP.values()} | {NARRATOR_EDGE_VOICE})

# kokoro-onnx: archetype → voice (zh voices: zf_xiaobei, zf_xiaoni, zm_yunxi, zm_yundong)
_KOKORO_MAP: dict[str, str] = {
    "导师":   "zm_yunxi",
    "盟友":   "zm_yunxi",
    "反派":   "zm_yundong",
    "神秘人": "zm_yundong",
    "商人":   "zm_yunxi",
    "守卫":   "zm_yundong",
    "平民":   "zf_xiaobei",
    "智者":   "zm_yunxi",
    "冷酷":   "zf_xiaobei",
    "温柔":   "zf_xiaobei",
    "活泼":   "zf_xiaoni",
    "邪恶":   "zm_yundong",
    "儿童":   "zf_xiaoni",
    "长老":   "zm_yunxi",
    "武将":   "zm_yundong",
    "贵族":   "zf_xiaobei",
}

_KOKORO_DEFAULT = "zf_xiaobei"
NARRATOR_KOKORO_VOICE = "zf_xiaobei"


def edge_voice_for_archetype(archetype: str) -> str:
    return _EDGE_MAP.get(archetype, _EDGE_DEFAULT)[0]


def edge_prosody_for_archetype(archetype: str) -> tuple[str, str]:
    """Return (rate, pitch_hz) for edge-tts prosody."""
    entry = _EDGE_MAP.get(archetype, _EDGE_DEFAULT)
    return entry[1], entry[2]


def kokoro_voice_for_archetype(archetype: str) -> str:
    return _KOKORO_MAP.get(archetype, _KOKORO_DEFAULT)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -v 2>&1 | head -30
```

Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/tts/ backend/tests/test_tts_engines.py
git commit -m "feat(tts): voice_map — archetype→edge/kokoro voice mapping"
```

---

### Task 2: edge-tts backend engine

**Files:**
- Create: `backend/src/dzmm/tts/edge_engine.py`
- Modify: `backend/pyproject.toml` (add edge-tts)
- Modify: `backend/tests/test_tts_engines.py` (add edge engine tests)

- [ ] **Step 1: Add edge-tts to pyproject.toml**

```toml
# backend/pyproject.toml — in dependencies list, add after "httpx>=0.27":
    "edge-tts>=6.1",
```

- [ ] **Step 2: Install edge-tts**

```bash
cd backend && .venv/bin/pip install "edge-tts>=6.1"
```

Expected output: `Successfully installed edge-tts-6.x.x`

- [ ] **Step 3: Write failing tests for edge engine**

Append to `backend/tests/test_tts_engines.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_edge_synthesize_returns_bytes():
    """edge engine should return non-empty bytes on success."""
    from dzmm.tts.edge_engine import synthesize as edge_synthesize

    fake_chunk_audio = {"type": "audio", "data": b"fakemp3data"}
    fake_chunk_meta = {"type": "WordBoundary", "data": {}}

    async def fake_stream():
        yield fake_chunk_meta
        yield fake_chunk_audio

    mock_communicate = MagicMock()
    mock_communicate.stream = fake_stream

    with patch("dzmm.tts.edge_engine.edge_tts.Communicate", return_value=mock_communicate):
        result = await edge_synthesize("你好世界", "zh-CN-XiaoxiaoNeural")

    assert result == b"fakemp3data"


@pytest.mark.asyncio
async def test_edge_synthesize_empty_text_returns_empty():
    from dzmm.tts.edge_engine import synthesize as edge_synthesize

    async def fake_stream():
        return
        yield  # make it an async generator

    mock_communicate = MagicMock()
    mock_communicate.stream = fake_stream

    with patch("dzmm.tts.edge_engine.edge_tts.Communicate", return_value=mock_communicate):
        result = await edge_synthesize("", "zh-CN-XiaoxiaoNeural")

    assert result == b""
```

- [ ] **Step 4: Run to confirm failure**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py::test_edge_synthesize_returns_bytes -v
```

Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 5: Implement edge_engine.py**

```python
# backend/src/dzmm/tts/edge_engine.py
"""edge-tts synthesis — calls Microsoft Neural TTS (free, online)."""
import io
import edge_tts


async def synthesize(
    text: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """Return MP3 bytes for *text* spoken with *voice*.

    rate: percent string, e.g. "+10%" or "-15%"
    pitch: Hz string, e.g. "+3Hz" or "-5Hz"
    """
    if not text.strip():
        return b""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -k "edge" -v
```

Expected: 3 tests PASS (2 new + existing voice map tests)

- [ ] **Step 7: Commit**

```bash
git add backend/src/dzmm/tts/edge_engine.py backend/pyproject.toml backend/tests/test_tts_engines.py
git commit -m "feat(tts): edge-tts synthesis engine"
```

---

### Task 3: kokoro-onnx backend engine

**Files:**
- Create: `backend/src/dzmm/tts/kokoro_engine.py`
- Modify: `backend/pyproject.toml` (add kokoro-onnx, soundfile)
- Modify: `backend/tests/test_tts_engines.py` (add kokoro tests)

- [ ] **Step 1: Add kokoro-onnx and soundfile to pyproject.toml**

```toml
# backend/pyproject.toml — in dependencies list:
    "kokoro-onnx>=0.4",
    "soundfile>=0.12",
```

- [ ] **Step 2: Install new deps**

```bash
cd backend && .venv/bin/pip install "kokoro-onnx>=0.4" "soundfile>=0.12"
```

Expected: both packages install successfully

- [ ] **Step 3: Write failing tests for kokoro engine**

Append to `backend/tests/test_tts_engines.py`:

```python
from pathlib import Path


def test_kokoro_model_ready_false_when_no_file(tmp_path):
    from dzmm.tts.kokoro_engine import is_model_ready
    assert is_model_ready(tmp_path) is False


def test_kokoro_model_ready_true_when_files_exist(tmp_path):
    from dzmm.tts.kokoro_engine import is_model_ready, MODEL_FILENAME, VOICES_FILENAME
    (tmp_path / MODEL_FILENAME).write_bytes(b"fake")
    (tmp_path / VOICES_FILENAME).write_bytes(b"fake")
    assert is_model_ready(tmp_path) is True


@pytest.mark.asyncio
async def test_kokoro_synthesize_returns_wav_bytes(tmp_path):
    """kokoro engine returns WAV bytes (numpy→soundfile)."""
    import numpy as np
    from dzmm.tts.kokoro_engine import synthesize as kokoro_synthesize, MODEL_FILENAME, VOICES_FILENAME

    fake_samples = np.zeros(22050, dtype=np.float32)  # 1 second silence
    fake_sample_rate = 22050

    # Create dummy model files so is_model_ready returns True
    (tmp_path / MODEL_FILENAME).write_bytes(b"fake")
    (tmp_path / VOICES_FILENAME).write_bytes(b"fake")

    mock_kokoro = MagicMock()
    mock_kokoro.create.return_value = (fake_samples, fake_sample_rate)

    with patch("dzmm.tts.kokoro_engine.Kokoro", return_value=mock_kokoro):
        result = await kokoro_synthesize("你好", "zf_xiaobei", models_dir=tmp_path)

    assert len(result) > 44  # at least WAV header (44 bytes)
    assert result[:4] == b"RIFF"  # WAV magic bytes
```

- [ ] **Step 4: Run to confirm failure**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -k "kokoro" -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 5: Implement kokoro_engine.py**

```python
# backend/src/dzmm/tts/kokoro_engine.py
"""kokoro-onnx synthesis — offline, ONNX-only, ~82MB model download."""
import asyncio
import io
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from dzmm.config import APP_DIR

MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices.bin"
_MODEL_REPO = "hexgrad/Kokoro-82M"
_DEFAULT_MODELS_DIR = APP_DIR / "models" / "tts"

# Module-level cache: one Kokoro instance per models_dir path
_instances: dict[Path, Kokoro] = {}


def is_model_ready(models_dir: Path | None = None) -> bool:
    d = models_dir or _DEFAULT_MODELS_DIR
    return (d / MODEL_FILENAME).exists() and (d / VOICES_FILENAME).exists()


async def ensure_model(models_dir: Path | None = None) -> None:
    """Download model files if not already present. Raises on failure."""
    d = models_dir or _DEFAULT_MODELS_DIR
    if is_model_ready(d):
        return
    d.mkdir(parents=True, exist_ok=True)
    # Use huggingface_hub (already a transitive dep via chromadb)
    from huggingface_hub import hf_hub_download
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: hf_hub_download(_MODEL_REPO, MODEL_FILENAME, local_dir=str(d)),
    )
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: hf_hub_download(_MODEL_REPO, VOICES_FILENAME, local_dir=str(d)),
    )


def _get_instance(models_dir: Path) -> Kokoro:
    if models_dir not in _instances:
        _instances[models_dir] = Kokoro(
            str(models_dir / MODEL_FILENAME),
            str(models_dir / VOICES_FILENAME),
        )
    return _instances[models_dir]


async def synthesize(
    text: str,
    voice: str = "zf_xiaobei",
    speed: float = 1.0,
    models_dir: Path | None = None,
) -> bytes:
    """Return WAV bytes. Raises RuntimeError if model not downloaded."""
    d = models_dir or _DEFAULT_MODELS_DIR
    if not is_model_ready(d):
        raise RuntimeError("Kokoro model not downloaded — call ensure_model() first")
    if not text.strip():
        return b""

    kokoro = _get_instance(d)
    lang = "z" if voice.startswith("z") else "a"

    loop = asyncio.get_event_loop()
    samples, sample_rate = await loop.run_in_executor(
        None,
        lambda: kokoro.create(text, voice=voice, speed=speed, lang=lang),
    )

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()
```

- [ ] **Step 6: Run tests**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/dzmm/tts/kokoro_engine.py backend/pyproject.toml backend/tests/test_tts_engines.py
git commit -m "feat(tts): kokoro-onnx local synthesis engine with auto-download"
```

---

### Task 4: New TTS API endpoints

**Files:**
- Modify: `backend/src/dzmm/api/routes_tts.py`
- Modify: `backend/tests/test_tts_engines.py` (add API endpoint tests)

The existing `POST /tts` proxy endpoint stays unchanged. New endpoints:
- `GET /tts/voices` — list of edge-tts Chinese voice names with archetype tags
- `POST /tts/builtin` — edge-tts synthesis
- `GET /tts/kokoro/status` — `{ready: bool}`
- `POST /tts/kokoro/ensure` — trigger model download (blocks until done, ~82MB)
- `POST /tts/kokoro/synthesize` — kokoro synthesis

- [ ] **Step 1: Write failing API tests**

Append to `backend/tests/test_tts_engines.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


@pytest.fixture
async def http(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    maker = async_session(engine)
    app = create_app(maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_get_tts_voices_returns_list(http):
    r = await http.get("/tts/voices")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 8
    first = data[0]
    assert "voice" in first
    assert "label" in first


async def test_tts_builtin_edge_calls_engine(http):
    with patch("dzmm.api.routes_tts.edge_synthesize", new=AsyncMock(return_value=b"mp3bytes")) as m:
        r = await http.post("/tts/builtin", json={"text": "你好", "voice": "zh-CN-XiaoxiaoNeural"})
    assert r.status_code == 200
    assert r.content == b"mp3bytes"
    m.assert_called_once()


async def test_tts_builtin_edge_empty_text_returns_204(http):
    with patch("dzmm.api.routes_tts.edge_synthesize", new=AsyncMock(return_value=b"")):
        r = await http.post("/tts/builtin", json={"text": "   ", "voice": "zh-CN-XiaoxiaoNeural"})
    assert r.status_code == 204


async def test_tts_kokoro_status_returns_ready_flag(http):
    with patch("dzmm.api.routes_tts.is_kokoro_ready", return_value=False):
        r = await http.get("/tts/kokoro/status")
    assert r.status_code == 200
    assert r.json()["ready"] is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -k "http" -v
```

Expected: FAIL — 404 or import errors

- [ ] **Step 3: Rewrite routes_tts.py**

```python
# backend/src/dzmm/api/routes_tts.py
"""TTS routes: proxy (existing), edge-tts builtin, kokoro-onnx local."""
from unittest.mock import patch  # imported in test shims only — remove this line
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

# ---------------------------------------------------------------------------
# Existing proxy endpoint (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Voice listing
# ---------------------------------------------------------------------------

_VOICE_LABELS = {
    "zh-CN-XiaoxiaoNeural":  "晓晓（温柔/旁白）",
    "zh-CN-XiaohanNeural":   "晓涵（活泼）",
    "zh-CN-XiaomoNeural":    "晓墨（冷静）",
    "zh-CN-XiaoqiuNeural":   "晓秋（沉稳/智者）",
    "zh-CN-XiaoshuangNeural":"晓双（儿童）",
    "zh-CN-XiaoxuanNeural":  "晓萱（成熟女）",
    "zh-CN-XiaozhenNeural":  "晓甄（平民）",
    "zh-CN-YunfengNeural":   "云枫（守卫/武将）",
    "zh-CN-YunhaoNeural":    "云皓（青年男）",
    "zh-CN-YunjianNeural":   "云健（叙事男）",
    "zh-CN-YunxiNeural":     "云希（盟友）",
    "zh-CN-YunyangNeural":   "云扬（商人/权威）",
    "zh-CN-YunyeNeural":     "云野（导师/反派）",
}


@router.get("/voices")
async def list_edge_voices():
    """Return edge-tts Chinese voices with human-readable labels."""
    return [
        {"voice": v, "label": _VOICE_LABELS.get(v, v)}
        for v in sorted(set(EDGE_VOICES) | set(_VOICE_LABELS))
    ]


# ---------------------------------------------------------------------------
# edge-tts builtin endpoint
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# kokoro-onnx local endpoints
# ---------------------------------------------------------------------------

@router.get("/kokoro/status")
async def kokoro_status():
    return {"ready": is_kokoro_ready()}


@router.post("/kokoro/ensure")
async def kokoro_ensure():
    """Download kokoro model if not present. Blocks until done (~82 MB)."""
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
        raise HTTPException(503, "kokoro model not downloaded — call /tts/kokoro/ensure first")
    try:
        audio = await kokoro_synthesize(body.text, body.voice, body.speed)
    except Exception as e:
        raise HTTPException(500, f"kokoro synthesis failed: {e}")
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")
```

Note: remove the stray `from unittest.mock import patch` line at top — that was a comment artifact. The actual file should be:

```python
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
```

- [ ] **Step 4: Run all TTS tests**

```bash
cd backend && .venv/bin/pytest tests/test_tts_engines.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/api/routes_tts.py backend/tests/test_tts_engines.py
git commit -m "feat(tts): builtin edge-tts + kokoro API endpoints"
```

---

### Task 5: Frontend store + composable

**Files:**
- Modify: `frontend/src/stores/app.ts`
- Modify: `frontend/src/composables/useTTS.ts`

- [ ] **Step 1: Extend ttsMode type in app store**

In `frontend/src/stores/app.ts`, replace the ttsMode line:

```typescript
// BEFORE (line 54):
const ttsMode = ref<'webspeech' | 'local'>(loadTtsSetting('mode', 'webspeech') as 'webspeech' | 'local')

// AFTER:
const ttsMode = ref<'webspeech' | 'local' | 'edge' | 'kokoro'>(
  loadTtsSetting('mode', 'webspeech') as 'webspeech' | 'local' | 'edge' | 'kokoro'
)
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "error" | head -10
```

Expected: no new errors related to ttsMode

- [ ] **Step 3: Add edge + kokoro synthesize paths to useTTS.ts**

Replace the entire `useTTS.ts` with:

```typescript
// frontend/src/composables/useTTS.ts
import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { backendOrigin } from '@/api/client'

export interface TtsVoiceMap {
  narrator: string
  pc: string
  [npcName: string]: string
}

interface Segment {
  speaker: string
  text: string
}

const NARRATIVE_RE = /<narrative>([\s\S]*?)<\/narrative>/g
const SAY_RE = /<say\s+speaker="([^"]+)">([\s\S]*?)<\/say>/g
const PC_ACTION_RE = /<pc_action>([\s\S]*?)<\/pc_action>/g

function parseSegments(rawContent: string): Segment[] {
  const all: { index: number; segment: Segment }[] = []
  let m: RegExpExecArray | null

  NARRATIVE_RE.lastIndex = 0
  while ((m = NARRATIVE_RE.exec(rawContent))) {
    const text = m[1].trim()
    if (text) all.push({ index: m.index, segment: { speaker: 'narrator', text } })
  }
  SAY_RE.lastIndex = 0
  while ((m = SAY_RE.exec(rawContent))) {
    const text = m[2].trim()
    if (text) all.push({ index: m.index, segment: { speaker: m[1], text } })
  }
  PC_ACTION_RE.lastIndex = 0
  while ((m = PC_ACTION_RE.exec(rawContent))) {
    const text = m[1].trim()
    if (text) all.push({ index: m.index, segment: { speaker: 'pc', text } })
  }
  all.sort((a, b) => a.index - b.index)
  return all.map((x) => x.segment)
}

// Voice strings for edge mode can optionally encode rate+pitch:
// "zh-CN-XiaomoNeural" or "zh-CN-XiaomoNeural|-10%|-3Hz"
function parseEdgeVoice(v: string): { voice: string; rate: string; pitch: string } {
  const parts = v.split('|')
  return { voice: parts[0], rate: parts[1] ?? '+0%', pitch: parts[2] ?? '+0Hz' }
}

let _audioCtx: AudioContext | null = null
function getAudioCtx(): AudioContext {
  if (!_audioCtx || _audioCtx.state === 'closed') _audioCtx = new AudioContext()
  return _audioCtx
}

const _speaking = ref(false)
let _aborted = false
let _abortCtrl: AbortController | null = null
let _activeSource: AudioBufferSourceNode | null = null

async function _getVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === 'undefined' || !window.speechSynthesis) return []
  const voices = window.speechSynthesis.getVoices()
  if (voices.length) return voices
  return new Promise((resolve) => {
    window.speechSynthesis.addEventListener('voiceschanged', () => resolve(window.speechSynthesis.getVoices()), { once: true })
  })
}

export function useTTS() {
  const appStore = useAppStore()

  function stop() {
    _aborted = true
    _abortCtrl?.abort()
    _activeSource?.stop()
    _activeSource = null
    _speaking.value = false
    if (typeof window !== 'undefined' && window.speechSynthesis) window.speechSynthesis.cancel()
  }

  async function _speakWebSpeech(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    const voices = await _getVoices()
    function findVoice(name: string): SpeechSynthesisVoice | null {
      if (!name) return null
      return voices.find((v) => v.name === name || v.voiceURI === name) ?? null
    }
    for (const seg of segments) {
      if (_aborted) break
      const voiceName = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? ''
      const utterance = new SpeechSynthesisUtterance(seg.text)
      const voice = findVoice(voiceName)
      if (voice) utterance.voice = voice
      utterance.lang = voice?.lang ?? 'zh-CN'
      await new Promise<void>((resolve) => {
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
      })
    }
  }

  async function _playAudioBytes(audioData: ArrayBuffer): Promise<void> {
    const ctx = getAudioCtx()
    if (ctx.state === 'suspended') await ctx.resume()
    const decoded = await ctx.decodeAudioData(audioData)
    const source = ctx.createBufferSource()
    source.buffer = decoded
    source.connect(ctx.destination)
    _activeSource = source
    await new Promise<void>((resolve) => {
      source.onended = () => resolve()
      source.start()
    })
    _activeSource = null
  }

  async function _speakLocal(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    const ctx = getAudioCtx()
    if (ctx.state === 'suspended') await ctx.resume()
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'default'
      try {
        const resp = await fetch(`${backendOrigin}/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_config_id: appStore.ttsModelConfigId, text: seg.text, voice }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok) continue
        await _playAudioBytes(await resp.arrayBuffer())
      } catch { /* skip segment */ }
    }
  }

  async function _speakEdge(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    for (const seg of segments) {
      if (_aborted) break
      const rawVoice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'zh-CN-XiaoxiaoNeural'
      const { voice, rate, pitch } = parseEdgeVoice(rawVoice)
      try {
        const resp = await fetch(`${backendOrigin}/tts/builtin`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: seg.text, voice, rate, pitch }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok || resp.status === 204) continue
        await _playAudioBytes(await resp.arrayBuffer())
      } catch { /* skip segment */ }
    }
  }

  async function _speakKokoro(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'zf_xiaobei'
      try {
        const resp = await fetch(`${backendOrigin}/tts/kokoro/synthesize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: seg.text, voice }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok || resp.status === 204) continue
        await _playAudioBytes(await resp.arrayBuffer())
      } catch { /* skip segment */ }
    }
  }

  async function playTurn(rawContent: string | undefined, voiceMap: TtsVoiceMap): Promise<void> {
    if (!appStore.ttsEnabled || !rawContent) return
    if (appStore.muted) return

    stop()
    _aborted = false
    _abortCtrl = new AbortController()
    _speaking.value = true

    const segments = parseSegments(rawContent)
    if (!segments.length) {
      _speaking.value = false
      return
    }

    try {
      if (appStore.ttsMode === 'webspeech') {
        await _speakWebSpeech(segments, voiceMap)
      } else if (appStore.ttsMode === 'edge') {
        await _speakEdge(segments, voiceMap)
      } else if (appStore.ttsMode === 'kokoro') {
        await _speakKokoro(segments, voiceMap)
      } else {
        await _speakLocal(segments, voiceMap)
      }
    } finally {
      _speaking.value = false
    }
  }

  return { playTurn, stop, speaking: _speaking }
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "error" | head -10
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/app.ts frontend/src/composables/useTTS.ts
git commit -m "feat(tts): extend store + useTTS composable for edge/kokoro modes"
```

---

### Task 6: TTS settings card UI

**Files:**
- Modify: `frontend/src/components/TtsSettingsCard.vue`

The card needs:
1. 4 mode radio buttons (webspeech / local / edge / kokoro)
2. For `edge` mode: voice dropdown fetched from `/tts/voices`, separate for GM/PC
3. For `kokoro` mode: download button + progress/status indicator, GM/PC voice selects
4. Edge voice strings stored as `"voiceName|rate|pitch"` so archetype prosody is preserved

- [ ] **Step 1: Rewrite TtsSettingsCard.vue**

```vue
<!-- frontend/src/components/TtsSettingsCard.vue -->
<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { backendOrigin } from '@/api/client'

const appStore = useAppStore()
const modelsStore = useModelConfigsStore()

// webspeech
const webSpeechVoices = ref<{ name: string; lang: string }[]>([])

// edge-tts
const edgeVoices = ref<{ voice: string; label: string }[]>([])

// kokoro
const kokoroReady = ref<boolean | null>(null)
const kokoroDownloading = ref(false)
const kokoroError = ref('')

const KOKORO_ZH_VOICES = [
  { value: 'zf_xiaobei', label: '小北（中文女，温柔）' },
  { value: 'zf_xiaoni',  label: '小妮（中文女，活泼）' },
  { value: 'zm_yunxi',   label: '云希（中文男，稳重）' },
  { value: 'zm_yundong', label: '云动（中文男，低沉）' },
]

onMounted(async () => {
  await modelsStore.refresh()

  if (typeof window !== 'undefined' && window.speechSynthesis) {
    const load = () => {
      webSpeechVoices.value = window.speechSynthesis.getVoices().map((v) => ({ name: v.name, lang: v.lang }))
    }
    load()
    window.speechSynthesis.onvoiceschanged = load
  }

  try {
    const r = await fetch(`${backendOrigin}/tts/voices`)
    if (r.ok) edgeVoices.value = await r.json()
  } catch { /* ignore */ }

  await refreshKokoroStatus()
})

async function refreshKokoroStatus() {
  try {
    const r = await fetch(`${backendOrigin}/tts/kokoro/status`)
    if (r.ok) kokoroReady.value = (await r.json()).ready
  } catch { kokoroReady.value = false }
}

async function downloadKokoro() {
  kokoroDownloading.value = true
  kokoroError.value = ''
  try {
    const r = await fetch(`${backendOrigin}/tts/kokoro/ensure`, { method: 'POST' })
    if (r.ok) {
      kokoroReady.value = true
    } else {
      const body = await r.json().catch(() => ({ detail: r.statusText }))
      kokoroError.value = body.detail ?? '下载失败'
    }
  } catch (e: any) {
    kokoroError.value = e?.message ?? '网络错误'
  } finally {
    kokoroDownloading.value = false
  }
}

const chineseVoices = computed(() =>
  webSpeechVoices.value.filter((v) => v.lang.startsWith('zh') || v.lang.startsWith('cmn')),
)
const otherVoices = computed(() =>
  webSpeechVoices.value.filter((v) => !v.lang.startsWith('zh') && !v.lang.startsWith('cmn')),
)

function save() { appStore.saveTtsSettings() }
</script>

<template>
  <el-card>
    <template #header>
      <strong>🔊 语音朗读（TTS）</strong>
    </template>
    <el-form label-width="110px" class="space-y-2 text-sm">

      <el-form-item label="启用 TTS">
        <el-switch v-model="appStore.ttsEnabled" @change="save" />
      </el-form-item>

      <template v-if="appStore.ttsEnabled">
        <el-form-item label="朗读模式">
          <el-radio-group v-model="appStore.ttsMode" @change="save">
            <el-radio value="edge">内置 edge-tts（在线免费，Neural音色）</el-radio>
            <el-radio value="kokoro">本地 Kokoro（离线，需下载 ~82MB）</el-radio>
            <el-radio value="webspeech">浏览器内置（Web Speech API）</el-radio>
            <el-radio value="local">外部 TTS 服务（OpenAI 兼容）</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- edge-tts mode -->
        <template v-if="appStore.ttsMode === 'edge'">
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="save" placeholder="晓晓（温柔/旁白）" clearable filterable>
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="save" placeholder="与旁白相同" clearable filterable>
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
          <div class="text-xs text-slate-400 pl-1">
            NPC 音色在游戏中「NPC 图鉴」里设置；新 NPC 会按性格原型自动分配。
          </div>
        </template>

        <!-- kokoro mode -->
        <template v-if="appStore.ttsMode === 'kokoro'">
          <el-form-item label="模型状态">
            <div class="flex items-center gap-3">
              <el-tag v-if="kokoroReady === true" type="success">已就绪</el-tag>
              <el-tag v-else-if="kokoroReady === false" type="info">未下载</el-tag>
              <el-tag v-else type="warning">检测中…</el-tag>
              <el-button
                v-if="!kokoroReady"
                type="primary"
                size="small"
                :loading="kokoroDownloading"
                @click="downloadKokoro"
              >
                {{ kokoroDownloading ? '下载中… (~82MB)' : '立即下载' }}
              </el-button>
            </div>
            <div v-if="kokoroError" class="text-xs text-red-500 mt-1">{{ kokoroError }}</div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="save" placeholder="小北（中文女，温柔）" clearable>
              <el-option v-for="v in KOKORO_ZH_VOICES" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="save" placeholder="与旁白相同" clearable>
              <el-option v-for="v in KOKORO_ZH_VOICES" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
          </el-form-item>
        </template>

        <!-- webspeech mode -->
        <template v-if="appStore.ttsMode === 'webspeech'">
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="save" placeholder="系统默认" clearable filterable>
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="save" placeholder="与旁白相同" clearable filterable>
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </el-form-item>
        </template>

        <!-- local proxy mode -->
        <template v-if="appStore.ttsMode === 'local'">
          <el-form-item label="TTS 模型配置">
            <el-select v-model="appStore.ttsModelConfigId" @change="save" placeholder="选择模型配置">
              <el-option v-for="m in modelsStore.items" :key="m.id" :label="`${m.name} (${m.model_name})`" :value="m.id" />
            </el-select>
            <div class="text-xs text-slate-400 mt-1">
              在「模型配置」中添加 TTS 服务的 base_url 与 model_name（如 kokoro / tts-1）。
            </div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-input v-model="appStore.ttsGmVoice" @change="save" placeholder="如 af_sky / zh_female_1" />
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-input v-model="appStore.ttsPcVoice" @change="save" placeholder="如 zh_male_1" />
          </el-form-item>
        </template>

        <div v-if="appStore.ttsMode !== 'local'" class="text-xs text-slate-400 pl-1">
          各 NPC 的专属音色可在游戏中的「NPC 图鉴」里单独设置；新 NPC 会按性格原型自动分配。
        </div>
      </template>
    </el-form>
  </el-card>
</template>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "error" | head -10
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TtsSettingsCard.vue
git commit -m "feat(tts): TtsSettingsCard — 4 modes, kokoro download UI, edge voice dropdown"
```

---

### Task 7: NPC archetype → auto voice preset in NpcDetailDialog

**Files:**
- Modify: `frontend/src/components/NpcDetailDialog.vue`

When the NPC has an `archetype` and no `tts_voice` set, show the auto-assigned voice name as placeholder. In edge mode, replace the free-text input with a dropdown. Add an "按性格自动分配" button that calls the backend to set the voice based on archetype.

The backend already has `/sessions/{id}/npcs/{npc_id}/voice` PATCH endpoint. We only need a new `GET /tts/voice-for-archetype` endpoint to suggest a voice — or we can do the mapping in the frontend (cleaner, no extra endpoint).

**Client-side archetype → voice mapping** (keeps it simple, no extra endpoint):

- [ ] **Step 1: Add archetype voice logic to NpcDetailDialog.vue**

Find the TTS section (around line 268) in `frontend/src/components/NpcDetailDialog.vue` and replace the entire `<section v-if="appStore.ttsEnabled">` block:

```vue
<section v-if="appStore.ttsEnabled">
  <h4 class="text-sm font-bold text-slate-600 mb-1">TTS 音色</h4>

  <!-- edge mode: dropdown -->
  <template v-if="appStore.ttsMode === 'edge'">
    <el-select
      :model-value="local.tts_voice ?? ''"
      :disabled="voiceSaving"
      placeholder="自动（按性格原型）"
      clearable
      filterable
      @change="(v: string) => saveVoice(v)"
      @clear="saveVoice('')"
    >
      <el-option label="自动（按性格原型）" value="" />
      <el-option v-for="v in edgeVoiceOptions" :key="v.voice" :label="v.label" :value="v.voice" />
    </el-select>
    <div class="text-xs text-slate-400 mt-1">
      留空则根据「{{ local.archetype || '性格原型' }}」自动分配：{{ autoVoiceLabel }}
    </div>
  </template>

  <!-- kokoro mode: dropdown -->
  <template v-else-if="appStore.ttsMode === 'kokoro'">
    <el-select
      :model-value="local.tts_voice ?? ''"
      :disabled="voiceSaving"
      placeholder="自动（按性格原型）"
      clearable
      @change="(v: string) => saveVoice(v)"
      @clear="saveVoice('')"
    >
      <el-option label="自动（按性格原型）" value="" />
      <el-option v-for="v in KOKORO_VOICE_OPTIONS" :key="v.value" :label="v.label" :value="v.value" />
    </el-select>
    <div class="text-xs text-slate-400 mt-1">
      留空则根据「{{ local.archetype || '性格原型' }}」自动分配：{{ autoKokoroVoiceLabel }}
    </div>
  </template>

  <!-- webspeech / local: free text -->
  <template v-else>
    <el-input
      :model-value="local.tts_voice ?? ''"
      :disabled="voiceSaving"
      placeholder="留空则使用旁白默认音色"
      clearable
      @change="(v: string) => saveVoice(v)"
      @clear="saveVoice('')"
    />
    <div class="text-xs text-slate-400 mt-1">
      本地模式填 voice 参数名（如 af_sky）；Web Speech 填音色全名。
    </div>
  </template>
</section>
```

And add the necessary script variables (add after existing imports/refs in `<script setup>`):

```typescript
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

// Edge voice options (static mirror of backend voice_map.py labels)
const edgeVoiceOptions = [
  { voice: 'zh-CN-XiaoxiaoNeural',   label: '晓晓（温柔/旁白）' },
  { voice: 'zh-CN-XiaohanNeural',    label: '晓涵（活泼）' },
  { voice: 'zh-CN-XiaomoNeural',     label: '晓墨（冷静）' },
  { voice: 'zh-CN-XiaoqiuNeural',    label: '晓秋（沉稳/智者）' },
  { voice: 'zh-CN-XiaoshuangNeural', label: '晓双（儿童）' },
  { voice: 'zh-CN-XiaozhenNeural',   label: '晓甄（平民）' },
  { voice: 'zh-CN-YunfengNeural',    label: '云枫（守卫/武将）' },
  { voice: 'zh-CN-YunxiNeural',      label: '云希（盟友）' },
  { voice: 'zh-CN-YunyangNeural',    label: '云扬（商人/权威）' },
  { voice: 'zh-CN-YunyeNeural',      label: '云野（导师/反派）' },
]

const KOKORO_VOICE_OPTIONS = [
  { value: 'zf_xiaobei', label: '小北（中文女，温柔）' },
  { value: 'zf_xiaoni',  label: '小妮（中文女，活泼）' },
  { value: 'zm_yunxi',   label: '云希（中文男，稳重）' },
  { value: 'zm_yundong', label: '云动（中文男，低沉）' },
]

// Archetype → edge voice (mirrors backend voice_map.py)
const ARCHETYPE_EDGE: Record<string, string> = {
  '导师': 'zh-CN-YunyeNeural', '盟友': 'zh-CN-YunxiNeural',
  '反派': 'zh-CN-YunyeNeural', '神秘人': 'zh-CN-XiaoqiuNeural',
  '商人': 'zh-CN-YunyangNeural', '守卫': 'zh-CN-YunfengNeural',
  '平民': 'zh-CN-XiaozhenNeural', '智者': 'zh-CN-XiaoqiuNeural',
  '冷酷': 'zh-CN-XiaomoNeural', '温柔': 'zh-CN-XiaoxiaoNeural',
  '活泼': 'zh-CN-XiaohanNeural', '邪恶': 'zh-CN-YunyeNeural',
  '儿童': 'zh-CN-XiaoshuangNeural',
}

const ARCHETYPE_KOKORO: Record<string, string> = {
  '导师': 'zm_yunxi', '盟友': 'zm_yunxi', '反派': 'zm_yundong',
  '神秘人': 'zm_yundong', '温柔': 'zf_xiaobei', '活泼': 'zf_xiaoni',
  '冷酷': 'zf_xiaobei', '邪恶': 'zm_yundong', '儿童': 'zf_xiaoni',
}

const autoVoiceLabel = computed(() => {
  const arch = local.value?.archetype ?? ''
  const voice = ARCHETYPE_EDGE[arch] ?? 'zh-CN-XiaoxiaoNeural'
  return edgeVoiceOptions.find((v) => v.voice === voice)?.label ?? voice
})

const autoKokoroVoiceLabel = computed(() => {
  const arch = local.value?.archetype ?? ''
  const voice = ARCHETYPE_KOKORO[arch] ?? 'zf_xiaobei'
  return KOKORO_VOICE_OPTIONS.find((v) => v.value === voice)?.label ?? voice
})
```

- [ ] **Step 2: Update GameView.vue voice map to use archetype auto-mapping**

In `frontend/src/views/GameView.vue`, find the voice map construction block (around line 218-230) and update it to use archetype mapping when the NPC has no explicit `tts_voice`:

```typescript
// BEFORE (existing code):
if (npc.tts_voice) map[npc.name] = npc.tts_voice

// AFTER — add archetype fallback for edge and kokoro modes:
if (npc.tts_voice) {
  map[npc.name] = npc.tts_voice
} else if (appStore.ttsMode === 'edge' && npc.archetype) {
  const archetypeEdge: Record<string, string> = {
    '导师': 'zh-CN-YunyeNeural', '盟友': 'zh-CN-YunxiNeural',
    '反派': 'zh-CN-YunyeNeural', '神秘人': 'zh-CN-XiaoqiuNeural',
    '商人': 'zh-CN-YunyangNeural', '守卫': 'zh-CN-YunfengNeural',
    '平民': 'zh-CN-XiaozhenNeural', '智者': 'zh-CN-XiaoqiuNeural',
    '冷酷': 'zh-CN-XiaomoNeural', '温柔': 'zh-CN-XiaoxiaoNeural',
    '活泼': 'zh-CN-XiaohanNeural', '邪恶': 'zh-CN-YunyeNeural',
    '儿童': 'zh-CN-XiaoshuangNeural',
  }
  if (archetypeEdge[npc.archetype]) map[npc.name] = archetypeEdge[npc.archetype]
} else if (appStore.ttsMode === 'kokoro' && npc.archetype) {
  const archetypeKokoro: Record<string, string> = {
    '导师': 'zm_yunxi', '盟友': 'zm_yunxi', '反派': 'zm_yundong',
    '神秘人': 'zm_yundong', '温柔': 'zf_xiaobei', '活泼': 'zf_xiaoni',
    '冷酷': 'zf_xiaobei', '邪恶': 'zm_yundong', '儿童': 'zf_xiaoni',
  }
  if (archetypeKokoro[npc.archetype]) map[npc.name] = archetypeKokoro[npc.archetype]
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i "error" | head -10
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NpcDetailDialog.vue frontend/src/views/GameView.vue
git commit -m "feat(tts): NPC archetype auto-voice in dialog + GameView voice map"
```

---

### Task 8: Build config updates

**Files:**
- Modify: `backend/dzmm-backend.spec`

kokoro-onnx uses ONNX Runtime and soundfile — both need PyInstaller hidden import entries.

- [ ] **Step 1: Add kokoro + soundfile hidden imports to spec**

In `backend/dzmm-backend.spec`, after the existing `hidden += collect_submodules('keyring.backends')` block, add:

```python
# edge-tts: uses asyncio websocket client — no hidden imports needed beyond standard library
hidden += ['edge_tts', 'edge_tts.communicate']

# kokoro-onnx: ONNX-based, no torch required
hidden += collect_submodules('kokoro_onnx')
hidden += ['soundfile', 'soundfile._soundfile']
```

- [ ] **Step 2: Verify spec parses without error**

```bash
cd backend && python -c "exec(open('dzmm-backend.spec').read().replace('from PyInstaller', '#from PyInstaller').replace('block_cipher = None','block_cipher = None\nfrom PyInstaller.utils.hooks import collect_submodules'))"
```

Expected: no Python syntax errors (just `NameError` for `Analysis`/`PYZ`/`EXE`/`COLLECT` which is expected outside PyInstaller context)

- [ ] **Step 3: Commit**

```bash
git add backend/dzmm-backend.spec
git commit -m "build(spec): add edge-tts + kokoro-onnx + soundfile hidden imports"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| edge-tts backend engine | Task 2 |
| edge-tts Chinese Neural voices (~16) | Task 1 voice map + Task 4 `/tts/voices` |
| SSML style / prosody by archetype | Task 1 prosody map + Task 2 rate/pitch params |
| NPC archetype auto-assign voice (edge) | Task 7 |
| kokoro-onnx backend engine | Task 3 |
| Model download check (skip if exists) | Task 3 `is_model_ready()` |
| Model download trigger + error handling | Task 4 `/tts/kokoro/ensure` |
| Download progress UI | Task 6 — button state "下载中…" |
| Frontend edge mode option | Task 5 + Task 6 |
| Frontend kokoro mode option | Task 5 + Task 6 |
| NPC archetype auto-assign voice (kokoro) | Task 7 |
| Existing proxy mode unchanged | Task 4 (proxy_tts kept verbatim) |
| PyInstaller spec updated | Task 8 |

**Placeholder scan:** No TBD/TODO/placeholder patterns found.

**Type consistency:**
- `ttsMode` type extended consistently in `app.ts` and consumed in `useTTS.ts` and `TtsSettingsCard.vue`
- `edge_synthesize` / `kokoro_synthesize` imported with aliases to avoid collision in `routes_tts.py`
- `is_model_ready` / `ensure_model` from `kokoro_engine` aliased as `is_kokoro_ready` / `ensure_kokoro_model` in routes
- Voice map constants mirrored in frontend (NpcDetailDialog, GameView) match the Python `voice_map.py` exactly
