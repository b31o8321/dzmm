"""File-rotating logger for dzmm.

Importing and calling setup_logging() once during app startup wires both the
stdlib root logger and uvicorn's access/error loggers to:
- a rotating file at ~/.dzmm/dzmm.log (5MB x 3)
- the existing stderr (so console output unchanged)
"""
# logging_config.py — 日志系统配置
# 本文件的职责：在应用启动时调用一次 setup_logging()，
# 此后所有模块用 logging.getLogger(__name__) 记录的日志，
# 都会同时写入 ~/.dzmm/dzmm.log 文件（带时间戳和级别），
# 并保留原来的终端输出（stderr）不变。
# 「只初始化一次」靠 _INITIALIZED 标志位保证，防止多次 import 导致重复添加 handler。

import logging          # Python 标准库：提供统一的日志接口（getLogger、Handler、Formatter 等）
import logging.handlers  # 标准库扩展：提供 RotatingFileHandler（按文件大小轮转的日志 handler）
from pathlib import Path

from dzmm.config import APP_DIR  # 用户数据目录（~/.dzmm），日志文件放在这里

# 日志文件的完整路径：~/.dzmm/dzmm.log
_LOG_PATH = APP_DIR / "dzmm.log"

# 全局标志位：记录日志系统是否已经初始化过
# 之所以用模块级变量而不是函数内变量，是因为模块只加载一次，变量会在整个进程生命周期内保持
_INITIALIZED = False


# ─────────────────────────────────────────────
# setup_logging：初始化日志系统
# 参数 level：日志级别（字符串），默认 "INFO"
#   - DEBUG：输出所有调试信息（开发时用）
#   - INFO：输出普通运行信息（生产默认）
#   - WARNING/ERROR：只输出警告或错误
# ─────────────────────────────────────────────
def setup_logging(level: str = "INFO") -> None:
    global _INITIALIZED  # 声明要修改模块级变量（Python 中修改全局变量必须先 global 声明）
    if _INITIALIZED:     # 如果已经初始化过，直接返回，避免重复添加 handler 导致日志重复打印
        return
    _INITIALIZED = True  # 标记为已初始化，后续调用直接跳过

    # 定义日志格式：「时间戳 级别（左对齐7字符） 模块名 :: 消息内容」
    # 例如：2026-05-10 12:34:56,789 INFO    dzmm.main :: seeded 3 builtin assets
    # %(asctime)s     — 格式化后的时间戳
    # %(levelname)-7s — 日志级别，左对齐、占7字符（"INFO   "、"WARNING"）
    # %(name)s        — logger 的名字，通常是模块名（如 dzmm.main）
    # %(message)s     — 实际的日志消息
    fmt = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
    formatter = logging.Formatter(fmt)  # 创建格式器对象，用于把日志记录转成上面的字符串

    # ── 创建轮转文件 Handler ──────────────────────────────────────────────────
    # RotatingFileHandler：当日志文件超过 maxBytes 时自动「滚动」
    #   - 把 dzmm.log 重命名为 dzmm.log.1
    #   - 把 dzmm.log.1 重命名为 dzmm.log.2（最多保留 backupCount=3 个备份）
    #   - 创建新的 dzmm.log 继续写入
    # 这样日志不会无限增大，最多占用 5MB × (1 + 3) = 20MB 磁盘空间
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_PATH,
        maxBytes=5 * 1024 * 1024,  # 单个日志文件最大 5MB（5 × 1024 × 1024 字节）
        backupCount=3,             # 最多保留 3 个备份文件（dzmm.log.1、.2、.3）
        encoding="utf-8",          # 强制 UTF-8 编码，支持中文日志内容
    )
    file_handler.setFormatter(formatter)  # 把格式器绑定到 handler，让写入文件的日志都用统一格式

    # ── 配置根 logger ──────────────────────────────────────────────────────────
    # 「根 logger」（root logger）是所有 logger 的父节点；
    # 子 logger（如 dzmm.main）如果没有自己的 handler，日志会「冒泡」到根 logger 处理。
    # 所以只需给根 logger 加一个 file_handler，整个应用的日志都会写入文件。
    root = logging.getLogger()       # 获取根 logger（不传名字 = 根 logger）
    root.setLevel(level.upper())     # 设置最低日志级别；低于此级别的日志会被丢弃，不会传给任何 handler
    root.addHandler(file_handler)    # 把文件 handler 绑定到根 logger

    # ── 也把日志写入 uvicorn 和 fastapi 的专属 logger ─────────────────────────
    # uvicorn 和 fastapi 默认用自己命名的 logger 记录请求日志和框架日志，
    # 它们不走根 logger，所以需要单独添加 handler。
    # propagate=True（默认值）：让日志继续往父 logger 传播，不阻断正常的 stderr 输出。
    # Also attach to uvicorn's named loggers so SSE / request logs land in the file.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)    # 获取 uvicorn/fastapi 各自的 logger
        log.addHandler(file_handler)     # 让它们的日志也写入文件
        log.propagate = True             # 保持传播，不截断（让 uvicorn 原有的终端输出继续工作）
