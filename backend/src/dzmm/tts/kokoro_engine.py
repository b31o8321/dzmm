# backend/src/dzmm/tts/kokoro_engine.py
"""kokoro-onnx synthesis — offline, ONNX-only, ~82MB model download."""
import asyncio
import io
from pathlib import Path

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
    await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: hf_hub_download(_MODEL_REPO, MODEL_FILENAME, local_dir=str(d)),
    )
    await asyncio.get_running_loop().run_in_executor(
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

    loop = asyncio.get_running_loop()
    samples, sample_rate = await loop.run_in_executor(
        None,
        lambda: kokoro.create(text, voice=voice, speed=speed, lang=lang),
    )

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()
