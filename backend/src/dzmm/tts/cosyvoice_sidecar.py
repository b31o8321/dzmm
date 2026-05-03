# backend/src/dzmm/tts/cosyvoice_sidecar.py
"""
CosyVoice sidecar manager.

Manages an isolated Python environment (via uv) that runs the CosyVoice TTS
server as a subprocess. Works on macOS, Linux, and Windows.

Workflow:
  1. is_installed()  → check venv + model present
  2. install()       → create uv venv, pip install deps, download model
  3. start()         → spawn server subprocess on localhost:5001
  4. stop()          → gracefully terminate subprocess
  5. is_running()    → subprocess poll check
"""
from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Callable

from dzmm.config import APP_DIR

_COSYVOICE_ENV_DIR = APP_DIR / "cosyvoice_env"
_MODEL_DIR = APP_DIR / "models" / "cosyvoice" / "CosyVoice-300M-Instruct"
_DEFAULT_PORT = 5001

# Server script location: in a PyInstaller bundle it lives under _MEIPASS/dzmm/tts/,
# otherwise it's next to this file in the source tree.
def _server_script_path() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return base / "cosyvoice_server_script.py"

# Module-level process handle.
_proc: subprocess.Popen | None = None  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# uv helpers
# ---------------------------------------------------------------------------

def _uv_exe() -> Path:
    """Return path to the uv binary, searching PATH then common install locations."""
    found = shutil.which("uv")
    if found:
        return Path(found)
    if platform.system() == "Windows":
        import os
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates = [
            local_app / "uv" / "bin" / "uv.exe",
            Path.home() / ".cargo" / "bin" / "uv.exe",
        ]
    else:
        candidates = [
            Path.home() / ".local" / "bin" / "uv",
            Path.home() / ".cargo" / "bin" / "uv",
        ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "(Windows: winget install --id=astral-sh.uv  or  irm https://astral.sh/uv/install.ps1 | iex)"
    )


def _python_exe() -> Path:
    """Python executable inside the cosyvoice venv."""
    if platform.system() == "Windows":
        return _COSYVOICE_ENV_DIR / "Scripts" / "python.exe"
    return _COSYVOICE_ENV_DIR / "bin" / "python"


# ---------------------------------------------------------------------------
# Public status helpers
# ---------------------------------------------------------------------------

def is_installed() -> bool:
    """True when the venv and model files are both present."""
    return _python_exe().exists() and (_MODEL_DIR / "cosyvoice2.yaml").exists()


def is_running() -> bool:
    """True when the sidecar subprocess is alive."""
    return _proc is not None and _proc.poll() is None


def port() -> int:
    return _DEFAULT_PORT


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

async def install(
    progress: Callable[[str], None] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that installs the CosyVoice environment.
    Yields progress strings.  Raises RuntimeError on failure.
    """
    def _emit(msg: str) -> None:
        if progress:
            progress(msg)

    uv = _uv_exe()

    # 1. Create venv
    if not _python_exe().exists():
        _emit("创建 Python 3.10 虚拟环境…")
        proc = await asyncio.create_subprocess_exec(
            str(uv), "venv", str(_COSYVOICE_ENV_DIR), "--python", "3.10",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"uv venv failed: {stderr.decode(errors='replace').strip()}")

    # 2. Install PyTorch (CPU wheel — works everywhere; user can swap for CUDA later)
    _emit("安装 PyTorch（CPU，约 300MB）…")
    torch_args = [
        str(uv), "pip", "install",
        "--python", str(_python_exe()),
        "torch", "torchaudio",
        "--index-url", "https://download.pytorch.org/whl/cpu",
    ]
    proc = await asyncio.create_subprocess_exec(
        *torch_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"PyTorch install failed: {stderr.decode(errors='replace').strip()}")

    # 3. Install CosyVoice and server dependencies
    _emit("安装 CosyVoice 依赖（约 500MB）…")
    cosy_args = [
        str(uv), "pip", "install",
        "--python", str(_python_exe()),
        "fastapi", "uvicorn[standard]", "pydantic>=2",
        "modelscope",
        # CosyVoice2 from official repo
        "git+https://github.com/FunAudioLLM/CosyVoice.git@main#subdirectory=.",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cosy_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"CosyVoice install failed: {stderr.decode(errors='replace').strip()}")

    # 4. Download model via modelscope (CosyVoice-300M-Instruct, ~1.8 GB)
    _emit("下载 CosyVoice-300M-Instruct 模型（约 1.8GB）…")
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    dl_code = (
        "from modelscope import snapshot_download; "
        f"snapshot_download('iic/CosyVoice-300M-Instruct', local_dir=r'{_MODEL_DIR}')"
    )
    proc = await asyncio.create_subprocess_exec(
        str(_python_exe()), "-c", dl_code,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Model download failed: {stderr.decode(errors='replace').strip()}")

    _emit("安装完成！")


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the CosyVoice sidecar subprocess (no-op if already running)."""
    global _proc
    if is_running():
        return
    if not is_installed():
        raise RuntimeError("CosyVoice not installed — call install() first")

    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW — no cmd window popup

    _proc = subprocess.Popen(
        [
            str(_python_exe()),
            str(_server_script_path()),
            "--port", str(_DEFAULT_PORT),
            "--model-dir", str(_MODEL_DIR),
        ],
        **kwargs,
    )


def stop() -> None:
    """Terminate the sidecar subprocess."""
    global _proc
    if _proc is None:
        return
    if _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None
