#!/usr/bin/env python3
# backend/src/dzmm/tts/cosyvoice_server_script.py
"""
CosyVoice TTS HTTP server - runs inside an isolated uv venv.

Start: python cosyvoice_server_script.py --port 5001 --model-dir /path/to/model
GET  /health          → {"ok": true, "model_loaded": bool}
POST /v1/audio/speech → WAV bytes   body: {"model": "...", "input": "text", "voice": "中文女"}
"""
import argparse
import io
import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="CosyVoice sidecar")

_cosyvoice = None
_model_dir: str = ""

VALID_VOICES = {"中文女", "中文男", "粤语女", "日语男", "英文女", "英文男", "韩语女"}


def _load_model(model_dir: str) -> None:
    global _cosyvoice, _model_dir
    import pathlib
    # CosyVoice-300M-Instruct is a v1 model (cosyvoice.yaml); use CosyVoice class.
    # CosyVoice2 models have cosyvoice2.yaml.
    if (pathlib.Path(model_dir) / "cosyvoice2.yaml").exists():
        from cosyvoice.cli.cosyvoice import CosyVoice2
        _cosyvoice = CosyVoice2(model_dir, load_jit=False)
    else:
        from cosyvoice.cli.cosyvoice import CosyVoice
        _cosyvoice = CosyVoice(model_dir, load_jit=False)
    _model_dir = model_dir


class SpeechRequest(BaseModel):
    model: str = "CosyVoice-300M-Instruct"
    input: str
    voice: str = "中文女"


@app.post("/v1/audio/speech")
async def synthesize(req: SpeechRequest) -> Response:
    if _cosyvoice is None:
        raise HTTPException(503, "model not loaded")
    if not req.input.strip():
        return Response(status_code=204)
    voice = req.voice if req.voice in VALID_VOICES else "中文女"
    try:
        import soundfile as sf
        buf = io.BytesIO()
        for result in _cosyvoice.inference_sft(req.input, voice, stream=False):
            audio = result["tts_speech"]
            # tensor shape: (1, N) or (N,) → numpy float32
            if hasattr(audio, "numpy"):
                audio = audio.squeeze().numpy()
            sf.write(buf, audio, _cosyvoice.sample_rate, format="WAV", subtype="PCM_16")
            break
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(500, f"synthesis error: {e}")


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _cosyvoice is not None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CosyVoice sidecar TTS server")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--model-dir", required=True, help="Path to CosyVoice-300M-Instruct directory")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"[cosyvoice] loading model from {args.model_dir} ...", flush=True)
    try:
        _load_model(args.model_dir)
    except Exception as e:
        print(f"[cosyvoice] model load failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[cosyvoice] ready on {args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
