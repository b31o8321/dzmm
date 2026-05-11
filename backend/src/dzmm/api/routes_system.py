# ============================================================
# routes_system.py — 系统状态探测 API
# ============================================================
#
# 【这个文件是做什么的？】
#   提供系统级别的状态检查接口，主要有三个用途：
#   1. 健康检查（/health）：告诉调用方"后端还活着"，并提供版本信息。
#   2. 系统状态（/system/status）：检测 Ollama 是否运行、是否安装。
#   3. 启动 Ollama（/system/ollama/start）：尝试在宿主机上拉起 Ollama 进程。
#
# 【什么是 Ollama？】
#   Ollama 是一个在本机运行大语言模型的工具，类似"本地版 ChatGPT 服务器"。
#   这个系统支持把 Ollama 作为 LLM 后端（不用联网、免费、数据不外流）。
#   但 Ollama 需要单独安装并启动，所以需要检测和管理它的状态。
#
# 【前端启动流程（Boot Gate）】
#   前端启动时会先调用 /health 确认后端已就绪，
#   再调用 /system/status 检查 Ollama 状态，
#   如果 Ollama 未运行就显示提示，用户点击后调用 /system/ollama/start 尝试启动。
#   所有这些检查通过后，才进入正常的游戏界面。

"""Host-system probes used by the frontend boot gate to give the user a
unified one-click experience: backend up → Ollama up → render app."""
import shutil      # shutil.which() — 在系统 PATH 里查找可执行文件，类似 Linux 的 which 命令
import subprocess  # subprocess.Popen() — 启动子进程
import sys         # sys.platform — 当前操作系统标识（'darwin'=macOS, 'win32'=Windows, 'linux'=Linux）

import httpx
from fastapi import APIRouter

# __version__ — 从包的 __init__.py 里导入当前版本号，如 "0.9.0"
from dzmm import __version__

# 系统相关接口挂载在 /system 路径下
router = APIRouter(prefix="/system", tags=["system"])

# /health 故意不加 /system 前缀，因为：
# 1. 历史兼容性：这个路径从 v0.x 就一直是 /health，改了会影响所有已有的部署脚本和监控配置
# 2. 惯例：/health 是行业通用的健康检查路径，简短易记
# 所以用单独的 health_router 不带前缀
health_router = APIRouter(tags=["system"])

# Ollama 默认的本地 API 地址（Ollama 启动后会在这个地址提供 REST API）
OLLAMA_URL = "http://localhost:11434/api/tags"


# GET /health
# 最简单的健康检查接口，返回 {"ok": True, "status": "ok", "version": "x.y.z"}
# 前端启动时轮询这个接口，直到后端启动完成
@health_router.get("/health")
async def health() -> dict:
    """Liveness probe + version surface. The frontend reads `version` to detect
    backend/frontend skew after a desktop upgrade."""
    # __version__ 让前端能检测版本是否匹配，防止前端和后端版本不一致导致的奇怪问题
    return {"ok": True, "status": "ok", "version": __version__}


# 内部函数：尝试访问 Ollama API，判断 Ollama 是否正在运行
# timeout=1.5 秒：这是一个快速探测，不希望等太久
async def _ollama_running(timeout: float = 1.5) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(OLLAMA_URL)
            return r.status_code == 200  # 200 表示 Ollama 正在运行且 API 正常
    except Exception:  # noqa: BLE001 — 任何异常（连接拒绝、超时等）都视为"未运行"
        return False


# GET /system/status
# 返回系统整体状态：后端状态、操作系统、Ollama 运行状态和安装状态
@router.get("/status")
async def status():
    return {
        "backend": "ok",            # 后端能响应请求，就说明后端正常
        "platform": sys.platform,   # 操作系统类型（前端可能需要据此显示不同的安装说明）
        "ollama": {
            "running": await _ollama_running(),                 # Ollama API 是否可达
            "installed": shutil.which("ollama") is not None,   # PATH 里是否有 ollama 命令
        },
    }


# POST /system/ollama/start
# 尝试在宿主机上启动 Ollama 进程。
# 「尽力而为」模式：函数立即返回（不等待 Ollama 完全启动），
# 调用方需要轮询 /system/status 来确认 Ollama 是否真的起来了。
@router.post("/ollama/start")
async def start_ollama():
    """Best-effort: try to launch the host's Ollama. Returns immediately
    after kicking off the launch; caller polls /system/status to confirm."""
    # 非 macOS 且找不到 ollama 命令，说明没安装，直接放弃
    if not shutil.which("ollama") and sys.platform != "darwin":
        # 在 macOS 上，Ollama.app 可能存在但 ollama 命令不在 PATH 里，
        # 所以 macOS 要单独处理，不能在这里直接返回失败
        return {"attempted": False, "reason": "ollama not installed"}

    try:
        if sys.platform == "darwin":
            # macOS：用 open -a Ollama 启动 GUI 应用，这样会正确显示菜单栏图标
            # subprocess.Popen 启动子进程后立即返回（不等待进程结束）
            # start_new_session=True 让子进程脱离当前进程组，即使后端关闭也不影响 Ollama
            subprocess.Popen(
                ["open", "-a", "Ollama"],   # macOS 的"打开应用"命令
                stdout=subprocess.DEVNULL,  # 丢弃标准输出，避免控制台被污染
                stderr=subprocess.DEVNULL,  # 丢弃标准错误
                start_new_session=True,     # 新会话，进程独立
            )
            return {"attempted": True, "method": "open -a Ollama"}

        if sys.platform == "win32":
            # Windows：直接启动 ollama.exe serve 子进程，但隐藏控制台窗口
            # On Windows ollama installs as a background service; if it's not
            # running we spawn a hidden ollama.exe process that owns its own console.
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW 标志，隐藏控制台窗口，用户看不到黑框
            )
            return {"attempted": True, "method": "ollama serve (hidden)"}

        # Linux 及其他系统：后台启动 ollama serve，并脱离当前会话
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # 脱离当前进程组，避免随 FastAPI 一起被 kill
        )
        return {"attempted": True, "method": "ollama serve (detached)"}

    except FileNotFoundError:
        # Popen 找不到 ollama 可执行文件（PATH 里没有），说明未安装
        return {"attempted": False, "reason": "ollama executable not found"}
    except Exception as e:  # noqa: BLE001 — 其他未预期的错误（权限问题等）
        return {"attempted": False, "reason": f"{type(e).__name__}: {e}"}
