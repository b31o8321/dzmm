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
# ============================================================
# CosyVoice Sidecar 管理器（cosyvoice_sidecar.py）
# ============================================================
# 【CosyVoice 是什么？】
#   CosyVoice 是阿里巴巴开源的高质量中文语音合成模型（TTS）。
#   相比 edge-tts（微软在线服务），CosyVoice 的特点：
#   - 本地运行（无需网络，速度快，隐私更好）
#   - 质量更高（支持声音克隆、情感控制、方言等）
#   - 但需要 GPU/强 CPU 和 1.8GB 模型文件
#
# 【为什么要单独开一个进程（Sidecar）？】
#   CosyVoice 依赖 PyTorch、特殊版本的 onnxruntime 等大型库，
#   与主应用的 Python 环境（FastAPI + SQLAlchemy）不兼容——
#   可能有相互冲突的依赖版本，或者需要 Python 3.10（主应用可能用 3.12）。
#
#   解决方案：把 CosyVoice 运行在一个**独立的子进程**里，
#   用独立的 Python 虚拟环境（venv），通过 HTTP API 通信。
#   主进程调用 http://localhost:5001/synthesize（由子进程提供），
#   子进程处理好后返回音频数据。
#   这种模式叫 "Sidecar"（边车），像摩托车旁边的边斗。
#
# 【Sidecar 的生命周期】
#   install() → 安装依赖、克隆代码、下载模型（只需要做一次）
#   start()   → 启动子进程（子进程运行 FastAPI 服务监听 5001 端口）
#   stop()    → 关闭子进程
#   is_installed() / is_running() → 状态查询
#
# 【subprocess.Popen 是什么？】
#   Python 的 subprocess 模块可以启动一个新的操作系统进程。
#   subprocess.Popen 是非阻塞的：主进程继续运行，子进程在后台独立执行。
#   主进程可以通过 _proc.poll() 检查子进程是否还在运行，
#   通过 _proc.terminate() 发送终止信号。
#   Java 里类似的是 ProcessBuilder + Process。
#
# 【PYTHONPATH 环境变量】
#   CosyVoice 不是普通的 pip 包（没有 setup.py/pyproject.toml），
#   无法用 pip install 安装。需要克隆源码，然后把源码目录加入 PYTHONPATH，
#   让 Python 能找到 `import cosyvoice` 语句。
# ============================================================
from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from dzmm.config import APP_DIR  # 应用数据目录（根据平台不同，如 ~/.local/share/dzmm）

# ── 常量：各种路径定义 ─────────────────────────────────────
# CosyVoice 的独立 Python 虚拟环境目录（与主应用完全隔离）
_COSYVOICE_ENV_DIR = APP_DIR / "cosyvoice_env"
# CosyVoice 源码克隆目录（git clone 的目标）
_COSYVOICE_SRC_DIR = APP_DIR / "cosyvoice_src"
# 模型文件目录（从 ModelScope 下载的 ~1.8GB 模型权重）
_MODEL_DIR = APP_DIR / "models" / "cosyvoice" / "CosyVoice-300M-Instruct"
# CosyVoice HTTP 服务监听的端口
_DEFAULT_PORT = 5001


def _server_script_path() -> Path:
    # 找到子进程要运行的 Python 脚本路径（cosyvoice_server_script.py）
    # 两种情况：
    # 1. 开发模式（从源码运行）：脚本在本文件旁边
    # 2. 打包模式（PyInstaller 打包的可执行文件）：脚本在 _MEIPASS 临时目录里
    import sys
    if getattr(sys, "frozen", False):   # frozen=True 表示是 PyInstaller 打包的
        base = Path(sys._MEIPASS)       # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent    # 和本文件同目录
    return base / "cosyvoice_server_script.py"


# 全局变量：保存子进程对象（None 表示未启动）
# 用全局变量是因为进程状态需要跨函数共享（start/stop/is_running 都要访问）
_proc: subprocess.Popen | None = None  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# uv helpers（uv 是高速的 Python 包管理工具）
# ---------------------------------------------------------------------------

def _uv_exe() -> Path:
    # 找到 uv 可执行文件的路径
    # uv 是 Rust 写的 Python 包管理工具（比 pip 快 10-100 倍）
    # 先用 shutil.which()（相当于 Linux 的 which 命令）在 PATH 里找
    found = shutil.which("uv")
    if found:
        return Path(found)

    # 如果 PATH 里没有，尝试常见的安装位置
    if platform.system() == "Windows":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates = [
            local_app / "uv" / "bin" / "uv.exe",
            Path.home() / ".cargo" / "bin" / "uv.exe",
        ]
    else:  # macOS / Linux
        candidates = [
            Path.home() / ".local" / "bin" / "uv",   # 默认安装位置
            Path.home() / ".cargo" / "bin" / "uv",   # Cargo 安装位置
        ]
    for c in candidates:
        if c.exists():
            return c
    # 找不到 uv，抛出错误并给出安装指引
    raise FileNotFoundError(
        "uv not found.\n"
        "  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "  Windows:     winget install astral-sh.uv"
    )


def _python_exe() -> Path:
    # 返回 CosyVoice 独立虚拟环境里的 python 可执行文件路径
    # Windows 和 Unix 的路径结构不同（Scripts vs bin）
    if platform.system() == "Windows":
        return _COSYVOICE_ENV_DIR / "Scripts" / "python.exe"
    return _COSYVOICE_ENV_DIR / "bin" / "python"


# ---------------------------------------------------------------------------
# Public status helpers（对外暴露的状态查询函数）
# ---------------------------------------------------------------------------

def is_installed() -> bool:
    # 检查 CosyVoice 是否已安装（三个条件全部满足才算安装完成）：
    # 1. Python 可执行文件存在（虚拟环境已创建）
    # 2. CosyVoice 源码目录存在（已 git clone）
    # 3. 模型配置文件存在（模型已下载）
    return (
        _python_exe().exists()
        and (_COSYVOICE_SRC_DIR / "cosyvoice").is_dir()
        and (_MODEL_DIR / "cosyvoice.yaml").exists()
    )


def is_running() -> bool:
    # 检查子进程是否正在运行
    # _proc.poll() 返回 None 表示进程还在运行
    # 返回退出码（整数）表示进程已退出
    return _proc is not None and _proc.poll() is None


def port() -> int:
    return _DEFAULT_PORT


# ---------------------------------------------------------------------------
# Install（安装 CosyVoice 环境）
# ---------------------------------------------------------------------------

async def _run(args: list[str], err_prefix: str, cwd: Path | None = None) -> None:
    # 异步运行一个命令行命令，等待完成
    # 如果命令返回非零退出码（失败），抛出 RuntimeError
    # asyncio.create_subprocess_exec 是异步版的 subprocess.Popen
    proc = await asyncio.create_subprocess_exec(
        *args,  # *args 把列表展开为位置参数（相当于 subprocess.run(args)）
        stdout=asyncio.subprocess.PIPE,  # 捕获标准输出
        stderr=asyncio.subprocess.PIPE, # 捕获标准错误
        cwd=str(cwd or APP_DIR),        # 工作目录
    )
    _, stderr = await proc.communicate()  # 等待进程结束，获取 stderr 内容
    if proc.returncode != 0:
        # 命令失败：截取 stderr 的最后 1000 字符（避免错误信息太长）
        raise RuntimeError(f"{err_prefix}: {stderr.decode(errors='replace').strip()[-1000:]}")


async def install(progress: Callable[[str], None] | None = None) -> None:
    """Install CosyVoice environment. Raises RuntimeError on failure."""
    import re  # 用于解析 requirements.txt

    def _emit(msg: str) -> None:
        # 进度回调：如果调用方提供了 progress 函数，调用它更新 UI 进度
        if progress:
            progress(msg)

    uv = _uv_exe()  # 找到 uv 的路径

    # 步骤 1：创建独立的 Python 3.10 虚拟环境
    # 为什么指定 3.10？CosyVoice 的依赖对 Python 版本有要求
    if not _python_exe().exists():
        _emit("创建 Python 3.10 虚拟环境…")
        await _run(
            [str(uv), "venv", str(_COSYVOICE_ENV_DIR), "--python", "3.10"],
            "uv venv failed",
        )

    # 步骤 2：克隆 CosyVoice 源码
    # --depth 1：只克隆最新的提交（浅克隆），不下载完整历史，速度快
    _emit("克隆 CosyVoice 源码…")
    if not (_COSYVOICE_SRC_DIR / "cosyvoice").is_dir():
        if _COSYVOICE_SRC_DIR.exists():
            shutil.rmtree(_COSYVOICE_SRC_DIR)  # 清理不完整的克隆
        await _run(
            [
                "git", "clone", "--depth", "1",
                "https://github.com/FunAudioLLM/CosyVoice.git",
                str(_COSYVOICE_SRC_DIR),
            ],
            "git clone failed",
            cwd=APP_DIR,
        )

    # 步骤 3：初始化 git submodules（CosyVoice 依赖 Matcha-TTS 子模块）
    # git submodule update --init：克隆所有子模块
    _emit("初始化 Matcha-TTS 子模块…")
    await _run(
        ["git", "submodule", "update", "--init", "--depth", "1"],
        "submodule init failed",
        cwd=_COSYVOICE_SRC_DIR,
    )

    # 步骤 4：安装 PyTorch CPU 版本
    # 从 requirements.txt 读取 CosyVoice 需要的 torch 版本，优先用它
    req_file = _COSYVOICE_SRC_DIR / "requirements.txt"
    torch_ver = "2.3.1"  # 兜底版本
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            m = re.match(r'^torch==([\d.]+)', line.strip())
            if m:
                torch_ver = m.group(1)
                break

    _emit(f"安装 PyTorch {torch_ver} CPU（~300MB）…")
    # 从 PyTorch 官方索引下载 CPU 版本（体积比 GPU 版小很多）
    await _run(
        [
            str(uv), "pip", "install",
            "--python", str(_python_exe()),   # 安装到独立虚拟环境
            f"torch=={torch_ver}", f"torchaudio=={torch_ver}",
            "--index-url", "https://download.pytorch.org/whl/cpu",  # PyTorch 官方 CPU 索引
        ],
        "PyTorch install failed",
    )

    # 步骤 5：安装 CosyVoice 其他依赖
    # 过滤掉 requirements.txt 里的：
    # - torch/torchaudio（已在上一步安装）
    # - 索引 URL 行（--extra-index-url 等）
    # - openai-whisper（需要特殊安装方式，下一步单独处理）
    if req_file.exists():
        _emit("安装 CosyVoice 依赖（约 500MB）…")
        skip_re = re.compile(
            r'^\s*(--(extra-)?index-url|--find-links)|'  # 跳过索引 URL 行
            r'^\s*torch(audio)?\s*[=<>!@]|'              # 跳过 torch/torchaudio
            r'^\s*openai-whisper',                         # 跳过 whisper（单独处理）
            re.I,
        )
        # 过滤后的有效依赖行
        filtered = [line for line in req_file.read_text().splitlines()
                    if line.strip() and not line.strip().startswith('#') and not skip_re.match(line)]
        # 把过滤后的依赖写入临时文件
        filtered_req = APP_DIR / "_cosy_req_filtered.txt"
        filtered_req.write_text('\n'.join(filtered))
        await _run(
            [
                str(uv), "pip", "install",
                "--python", str(_python_exe()),
                # 额外的 onnxruntime CUDA 索引（onnxruntime 的特定版本在这里）
                "--extra-index-url",
                "https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/",
                "--index-strategy", "unsafe-best-match",  # 允许跨索引搜索最佳版本
                "-r", str(filtered_req),
            ],
            "requirements install failed",
        )
        filtered_req.unlink(missing_ok=True)  # 删除临时文件（missing_ok=True：不存在也不报错）

    # 步骤 6：单独安装 openai-whisper
    # 需要 --no-build-isolation：因为 whisper 的 setup.py 依赖 pkg_resources，
    # 它必须能访问虚拟环境里的包，而不是独立的隔离构建环境
    _emit("安装 Whisper（语音前端）…")
    await _run(
        [
            str(uv), "pip", "install",
            "--python", str(_python_exe()),
            "--no-build-isolation",  # 禁用构建隔离（让 setup.py 能访问 venv 里的包）
            "openai-whisper==20231117",
        ],
        "whisper install failed",
    )

    # 步骤 7：安装子进程服务器的运行时依赖
    # fastapi/uvicorn：子进程 HTTP 服务
    # modelscope：用于下载模型（步骤 8 用）
    _emit("安装服务器运行时依赖…")
    await _run(
        [
            str(uv), "pip", "install",
            "--python", str(_python_exe()),
            "fastapi", "uvicorn[standard]", "pydantic>=2", "modelscope",
        ],
        "server deps install failed",
    )

    # 步骤 8：从 ModelScope（魔搭）下载模型权重（约 1.8GB）
    # 使用 Python 内联代码（-c 参数），调用 modelscope 的 snapshot_download
    _emit("下载 CosyVoice-300M-Instruct 模型（约 1.8GB）…")
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)  # 确保目录存在
    dl_code = (
        "from modelscope import snapshot_download; "
        f"snapshot_download('iic/CosyVoice-300M-Instruct', local_dir=r'{_MODEL_DIR}')"
    )
    env = _subprocess_env()  # 设置 PYTHONPATH（让子进程能 import cosyvoice）
    proc = await asyncio.create_subprocess_exec(
        str(_python_exe()), "-c", dl_code,  # 用独立虚拟环境的 python 执行
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
# Start / Stop（启动和停止 CosyVoice 子进程服务器）
# ---------------------------------------------------------------------------

def _subprocess_env() -> dict[str, str]:
    """构建带有 CosyVoice 路径的环境变量字典。

    CosyVoice 不是标准 pip 包，需要把源码目录和子模块目录加入 PYTHONPATH，
    这样子进程里才能正常 `import cosyvoice`。
    """
    env = os.environ.copy()  # 复制当前环境变量（保留 PATH 等重要变量）
    existing = env.get("PYTHONPATH", "")  # 获取现有的 PYTHONPATH（如果有）
    # 需要加入 PYTHONPATH 的路径：
    # 1. CosyVoice 根目录（包含 cosyvoice/ 包）
    # 2. Matcha-TTS 子模块目录（CosyVoice 内部依赖它）
    paths = [
        str(_COSYVOICE_SRC_DIR),
        str(_COSYVOICE_SRC_DIR / "third_party" / "Matcha-TTS"),
    ]
    extra = os.pathsep.join(paths)  # 用 : (Unix) 或 ; (Windows) 连接路径
    # 把新路径加到原有 PYTHONPATH 前面（优先级更高）
    env["PYTHONPATH"] = (extra + os.pathsep + existing) if existing else extra
    return env


def start() -> None:
    """启动 CosyVoice 子进程服务器。"""
    global _proc   # 声明修改全局变量（Python 要求写 global 才能在函数内修改全局变量）
    if is_running():
        return  # 已经在运行了，不重复启动
    if not is_installed():
        raise RuntimeError("CosyVoice not installed — call install() first")

    # 子进程的日志文件（把 stdout/stderr 都写到这里，方便排查问题）
    log_path = APP_DIR / "cosyvoice_sidecar.log"
    _log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115

    kwargs: dict = {
        "stdout": _log_file,  # 子进程的标准输出重定向到日志文件
        "stderr": _log_file,  # 子进程的标准错误也重定向到日志文件
        "env": _subprocess_env(),  # 带 PYTHONPATH 的环境变量
    }
    if platform.system() == "Windows":
        # Windows 特殊参数：不创建窗口（否则会弹出控制台窗口）
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    # 启动子进程：运行 cosyvoice_server_script.py
    # subprocess.Popen 是非阻塞的，主进程继续运行，子进程在后台执行
    _proc = subprocess.Popen(
        [
            str(_python_exe()),              # 独立虚拟环境的 python
            str(_server_script_path()),      # 子进程脚本
            "--port", str(_DEFAULT_PORT),    # HTTP 服务端口
            "--model-dir", str(_MODEL_DIR),  # 模型文件目录
        ],
        **kwargs,
    )


def stop() -> None:
    """停止 CosyVoice 子进程服务器。"""
    global _proc
    if _proc is None:
        return  # 没有子进程，什么都不做
    if _proc.poll() is None:    # poll() 返回 None 表示进程还在运行
        _proc.terminate()       # 发送 SIGTERM（优雅终止信号）
        try:
            _proc.wait(timeout=8)  # 等待最多 8 秒让进程自己退出
        except subprocess.TimeoutExpired:
            # 8 秒后还没退出，强制杀死（SIGKILL）
            _proc.kill()
    _proc = None  # 清空全局变量（表示子进程已停止）
