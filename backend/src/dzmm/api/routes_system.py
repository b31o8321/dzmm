"""Host-system probes used by the frontend boot gate to give the user a
unified one-click experience: backend up → Ollama up → render app."""
import shutil
import subprocess
import sys

import httpx
from fastapi import APIRouter

from dzmm import __version__

router = APIRouter(prefix="/system", tags=["system"])
# /health is intentionally exposed without the /system prefix so cheap liveness
# probes (frontend boot gate, deploy scripts, uptime monitors) keep the same
# URL they've used since v0.x.
health_router = APIRouter(tags=["system"])

OLLAMA_URL = "http://localhost:11434/api/tags"


@health_router.get("/health")
async def health() -> dict:
    """Liveness probe + version surface. The frontend reads `version` to detect
    backend/frontend skew after a desktop upgrade."""
    return {"ok": True, "status": "ok", "version": __version__}


async def _ollama_running(timeout: float = 1.5) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(OLLAMA_URL)
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get("/status")
async def status():
    return {
        "backend": "ok",
        "platform": sys.platform,
        "ollama": {
            "running": await _ollama_running(),
            "installed": shutil.which("ollama") is not None,
        },
    }


@router.post("/ollama/start")
async def start_ollama():
    """Best-effort: try to launch the host's Ollama. Returns immediately
    after kicking off the launch; caller polls /system/status to confirm."""
    if not shutil.which("ollama") and sys.platform != "darwin":
        # On macOS the .app bundle may exist without `ollama` on PATH.
        return {"attempted": False, "reason": "ollama not installed"}

    try:
        if sys.platform == "darwin":
            # Use `open` so the GUI .app launches normally (creates menu bar icon).
            subprocess.Popen(
                ["open", "-a", "Ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {"attempted": True, "method": "open -a Ollama"}

        if sys.platform == "win32":
            # On Windows ollama installs as a background service; if it's not
            # running we spawn a hidden ollama.exe process that owns its own console.
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            return {"attempted": True, "method": "ollama serve (hidden)"}

        # Linux / others
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"attempted": True, "method": "ollama serve (detached)"}
    except FileNotFoundError:
        return {"attempted": False, "reason": "ollama executable not found"}
    except Exception as e:  # noqa: BLE001
        return {"attempted": False, "reason": f"{type(e).__name__}: {e}"}
