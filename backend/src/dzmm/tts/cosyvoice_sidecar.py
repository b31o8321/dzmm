# backend/src/dzmm/tts/cosyvoice_sidecar.py
"""
CosyVoice sidecar manager.

CosyVoice is not an installable package (no pyproject.toml/setup.py at repo
root), so we git-clone the source and add it to PYTHONPATH at runtime.

Workflow:
  1. is_installed()  → check venv + cloned src + model present
  2. install()       → create uv venv, clone repo, pip install requirements,
                       download model via modelscope
  3. start()         → spawn server subprocess with PYTHONPATH set
  4. stop()          → gracefully terminate subprocess
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from dzmm.config import APP_DIR

_COSYVOICE_ENV_DIR = APP_DIR / "cosyvoice_env"
_COSYVOICE_SRC_DIR = APP_DIR / "cosyvoice_src"   # git clone destination
_MODEL_DIR = APP_DIR / "models" / "cosyvoice" / "CosyVoice-300M-Instruct"
_DEFAULT_PORT = 5001


def _server_script_path() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return base / "cosyvoice_server_script.py"


_proc: subprocess.Popen | None = None  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# uv helpers
# ---------------------------------------------------------------------------

def _uv_exe() -> Path:
    found = shutil.which("uv")
    if found:
        return Path(found)
    if platform.system() == "Windows":
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
        "uv not found.\n"
        "  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "  Windows:     winget install astral-sh.uv"
    )


def _python_exe() -> Path:
    if platform.system() == "Windows":
        return _COSYVOICE_ENV_DIR / "Scripts" / "python.exe"
    return _COSYVOICE_ENV_DIR / "bin" / "python"


# ---------------------------------------------------------------------------
# Public status helpers
# ---------------------------------------------------------------------------

def is_installed() -> bool:
    return (
        _python_exe().exists()
        and (_COSYVOICE_SRC_DIR / "cosyvoice").is_dir()
        and (_MODEL_DIR / "cosyvoice2.yaml").exists()
    )


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def port() -> int:
    return _DEFAULT_PORT


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

async def _run(args: list[str], err_prefix: str, cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd or APP_DIR),  # always use a known-good directory
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{err_prefix}: {stderr.decode(errors='replace').strip()[-1000:]}")


async def install(progress: Callable[[str], None] | None = None) -> None:
    """Install CosyVoice environment. Raises RuntimeError on failure."""
    import re

    def _emit(msg: str) -> None:
        if progress:
            progress(msg)

    uv = _uv_exe()

    # 1. Create venv with Python 3.10
    if not _python_exe().exists():
        _emit("创建 Python 3.10 虚拟环境…")
        await _run(
            [str(uv), "venv", str(_COSYVOICE_ENV_DIR), "--python", "3.10"],
            "uv venv failed",
        )

    # 2. Clone CosyVoice source first so we can read its requirements.txt
    _emit("克隆 CosyVoice 源码…")
    if not (_COSYVOICE_SRC_DIR / "cosyvoice").is_dir():
        if _COSYVOICE_SRC_DIR.exists():
            shutil.rmtree(_COSYVOICE_SRC_DIR)
        await _run(
            [
                "git", "clone", "--depth", "1",
                "https://github.com/FunAudioLLM/CosyVoice.git",
                str(_COSYVOICE_SRC_DIR),
            ],
            "git clone failed",
            cwd=APP_DIR,
        )

    # 3. Install PyTorch CPU pinned to the version CosyVoice needs.
    #    Read torch version from requirements.txt; fall back to 2.3.1.
    req_file = _COSYVOICE_SRC_DIR / "requirements.txt"
    torch_ver = "2.3.1"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            m = re.match(r'^torch==([\d.]+)', line.strip())
            if m:
                torch_ver = m.group(1)
                break

    _emit(f"安装 PyTorch {torch_ver} CPU（~300MB）…")
    await _run(
        [
            str(uv), "pip", "install",
            "--python", str(_python_exe()),
            f"torch=={torch_ver}", f"torchaudio=={torch_ver}",
            "--index-url", "https://download.pytorch.org/whl/cpu",
        ],
        "PyTorch install failed",
    )

    # 4. Install CosyVoice requirements, excluding:
    #    - torch/torchaudio (already installed above)
    #    - --extra-index-url / --index-url lines (we manage indexes ourselves)
    #    Add --index-strategy unsafe-best-match so uv searches all indexes for
    #    packages like onnxruntime==1.18.0 that only exist on a non-PyPI index.
    if req_file.exists():
        _emit("安装 CosyVoice 依赖（约 500MB）…")
        skip_re = re.compile(
            r'^\s*(--(extra-)?index-url|--find-links)|'
            r'^\s*torch(audio)?\s*[=<>!@]|'
            r'^\s*openai-whisper',  # no pkg_resources in uv isolated build
            re.I,
        )
        filtered = [l for l in req_file.read_text().splitlines()
                    if l.strip() and not l.strip().startswith('#') and not skip_re.match(l)]
        filtered_req = APP_DIR / "_cosy_req_filtered.txt"
        filtered_req.write_text('\n'.join(filtered))
        await _run(
            [
                str(uv), "pip", "install",
                "--python", str(_python_exe()),
                "--extra-index-url",
                "https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/",
                "--index-strategy", "unsafe-best-match",
                "-r", str(filtered_req),
            ],
            "requirements install failed",
        )
        filtered_req.unlink(missing_ok=True)

    # 5. Install server runtime deps (fastapi/uvicorn/modelscope may already be
    #    in requirements.txt but we ensure they're present regardless)
    _emit("安装服务器运行时依赖…")
    await _run(
        [
            str(uv), "pip", "install",
            "--python", str(_python_exe()),
            "fastapi", "uvicorn[standard]", "pydantic>=2", "modelscope",
        ],
        "server deps install failed",
    )

    # 6. Download model (~1.8 GB via modelscope)
    _emit("下载 CosyVoice-300M-Instruct 模型（约 1.8GB）…")
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    dl_code = (
        "from modelscope import snapshot_download; "
        f"snapshot_download('iic/CosyVoice-300M-Instruct', local_dir=r'{_MODEL_DIR}')"
    )
    # Set PYTHONPATH so modelscope can find cosyvoice if needed during download
    env = _subprocess_env()
    proc = await asyncio.create_subprocess_exec(
        str(_python_exe()), "-c", dl_code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(APP_DIR),
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Model download failed: {stderr.decode(errors='replace').strip()[-1000:]}")

    _emit("安装完成！")


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

def _subprocess_env() -> dict[str, str]:
    """Build env dict with PYTHONPATH pointing at the cloned CosyVoice source."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    src = str(_COSYVOICE_SRC_DIR)
    env["PYTHONPATH"] = (src + os.pathsep + existing) if existing else src
    return env


def start() -> None:
    global _proc
    if is_running():
        return
    if not is_installed():
        raise RuntimeError("CosyVoice not installed — call install() first")

    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": _subprocess_env(),
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

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
