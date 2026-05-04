# backend/src/dzmm/tts/kokoro_engine.py
"""kokoro-onnx synthesis — offline, ONNX-only, ~82MB model download."""
import asyncio
import io
from pathlib import Path

# Lazy import: kokoro_onnx pulls in phonemizer → espeak → language_tags at
# module load time (~0.3s + data files). Defer until first synthesis call so
# app startup is not penalised when user hasn't downloaded the model.
from dzmm.config import APP_DIR

MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices-v1.0.bin"
# Model files are on GitHub releases, NOT HuggingFace (hexgrad/Kokoro-82M has .pth, not .onnx)
_MODEL_BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_DEFAULT_MODELS_DIR = APP_DIR / "models" / "tts"

# Module-level cache: one Kokoro instance per models_dir path (lazy-loaded)
_instances: dict[Path, object] = {}


def is_model_ready(models_dir: Path | None = None) -> bool:
    d = models_dir or _DEFAULT_MODELS_DIR
    return (d / MODEL_FILENAME).exists() and (d / VOICES_FILENAME).exists()


async def _download_file(url: str, dest: Path) -> None:
    """Stream-download url → dest, resuming is not needed (files are <300MB)."""
    import httpx
    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    f.write(chunk)


async def ensure_model(models_dir: Path | None = None) -> None:
    """Download model files if not already present. Raises on failure."""
    d = models_dir or _DEFAULT_MODELS_DIR
    if is_model_ready(d):
        return
    d.mkdir(parents=True, exist_ok=True)
    for filename in (MODEL_FILENAME, VOICES_FILENAME):
        dest = d / filename
        if not dest.exists():
            await _download_file(f"{_MODEL_BASE_URL}/{filename}", dest)


def _get_instance(models_dir: Path) -> object:
    if models_dir not in _instances:
        from kokoro_onnx import Kokoro  # lazy: defers phonemizer/espeak import
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
    import soundfile as sf  # lazy: avoid soundfile import at startup
    d = models_dir or _DEFAULT_MODELS_DIR
    if not is_model_ready(d):
        raise RuntimeError("Kokoro model not downloaded — call ensure_model() first")
    if not text.strip():
        return b""

    kokoro = _get_instance(d)
    # Map voice prefix to espeak language code: z* = Mandarin (cmn), a* = English (en-us)
    lang = "cmn" if voice.startswith("z") else "en-us"

    loop = asyncio.get_running_loop()
    samples, sample_rate = await loop.run_in_executor(
        None,
        lambda: kokoro.create(text, voice=voice, speed=speed, lang=lang),  # type: ignore[union-attr]
    )

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()
