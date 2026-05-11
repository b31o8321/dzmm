"""PyInstaller entrypoint. Starts uvicorn synchronously."""
# main_entry.py — 应用程序的「真实入口」
# 本文件有两个使用场景：
#   1. 开发时直接运行：python -m dzmm.main_entry（或 uv run python main_entry.py）
#   2. PyInstaller 打包成可执行文件（.exe / .app）时，PyInstaller 会调用 main()
# 它的职责是：读取端口/host 环境变量 → 启动 uvicorn ASGI 服务器 → 让 FastAPI 开始接受请求
# 注意：uvicorn 本身支持异步，但 PyInstaller 入口需要同步函数，
# 所以用 asyncio.run() 把异步的 run() 包裹成同步调用。

import asyncio  # Python 标准库：提供事件循环，让异步代码能在普通同步环境中运行
import os       # 读取环境变量（端口号、监听地址）
import sys      # 访问命令行参数和进程退出码

import uvicorn  # 高性能 ASGI 服务器，负责监听 TCP 端口、解析 HTTP 请求、调用 FastAPI

from dzmm.logging_config import setup_logging  # 初始化日志（文件轮转 + 终端输出）
from dzmm.main import build_default_app        # 完整的应用构建函数（建库 + 种子数据 + FastAPI 组装）


def main():
    # 在 uvicorn 启动之前就初始化日志，确保启动过程中的日志也能被记录到文件
    setup_logging()

    # 从环境变量读取监听端口，默认 8765；int() 转换是因为环境变量总是字符串
    port = int(os.environ.get('DZMM_PORT', '8765'))
    # 默认只监听本机回环地址（127.0.0.1），外部设备无法直接访问，保证桌面应用的安全性
    # 如需局域网访问，可设置 DZMM_HOST=0.0.0.0
    host = os.environ.get('DZMM_HOST', '127.0.0.1')

    # 内部异步函数：先构建 FastAPI 应用，再启动 uvicorn 服务器
    # 之所以单独定义 async def run()，是因为 build_default_app() 是异步函数（它要做数据库 I/O），
    # 必须在事件循环里调用，不能直接在同步的 main() 里 await。
    async def run():
        app = await build_default_app()  # 异步初始化数据库、种子数据、NPC 记忆，然后返回 FastAPI 实例

        # uvicorn.Config：配置服务器参数，但此时还没有启动
        # log_level='info' 让 uvicorn 自己的访问日志也按 INFO 级别输出
        config = uvicorn.Config(app, host=host, port=port, log_level='info')

        # uvicorn.Server：根据 config 创建服务器对象
        server = uvicorn.Server(config)

        # serve()：真正开始监听端口，进入事件循环直到进程被终止（Ctrl+C 或系统信号）
        await server.serve()

    # asyncio.run()：创建一个全新的事件循环，运行 run() 协程直到它结束，然后关闭事件循环
    # 这是在同步代码里运行异步代码的标准方式
    asyncio.run(run())


# 当本文件被直接执行（python main_entry.py）时，__name__ == '__main__'，才调用 main()
# main() 正常结束返回 None，`None or 0` 得 0，sys.exit(0) 表示进程正常退出
if __name__ == '__main__':
    sys.exit(main() or 0)
