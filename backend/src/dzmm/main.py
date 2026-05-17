# main.py — FastAPI 应用的「工厂」模块
# 本文件负责两件事：
#   1. create_app()：接收一个数据库会话工厂，组装完整的 FastAPI 实例（注册中间件、路由、依赖注入）
#   2. build_default_app()：真正用于生产的入口，负责初始化数据库、植入种子数据、再调用 create_app()
# 把「创建」和「初始化」分开，是为了在测试时可以传入内存数据库，而不必改动路由逻辑。

import os
from collections.abc import AsyncIterator  # 异步迭代器类型，用于标注「yield 型」依赖函数的返回值
from pathlib import Path                   # 跨平台路径操作，比 os.path 更易读

from fastapi import FastAPI                             # FastAPI 框架核心类，所有路由都挂在它上面
from fastapi.middleware.cors import CORSMiddleware      # 跨域资源共享中间件，允许浏览器从不同源访问 API
from fastapi.staticfiles import StaticFiles             # 让 FastAPI 能直接托管静态文件（HTML/JS/CSS）
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # SQLAlchemy 异步会话相关类型

# 导入各业务模块的路由，每个 routes_xxx 文件定义一组相关 API 接口
from dzmm.api import (
    routes_assets,      # 素材（图片、音频等）的增删改查 + 上传
    routes_characters,  # 角色管理
    routes_factions,    # 派系管理
    routes_models,      # AI 模型配置
    routes_screenplay,  # 单个剧本的操作（生成、查看等）
    routes_screenplays, # 剧本列表
    routes_sessions,    # 游戏会话（跑团局）管理
    routes_system,      # 系统信息、健康检查
    routes_tts,         # 文字转语音代理
    routes_wizard,      # 新手向导（引导建档）
    routes_worlds,      # 世界观/世界设定管理
)
# 数据库底层工具：async_session 创建会话工厂，get_engine 创建数据库连接，init_db 建表
from dzmm.db.base import async_session, get_engine, init_db


# ─────────────────────────────────────────────
# create_app：纯组装函数，不做任何 I/O 操作
# 参数 session_maker：外部传入的数据库会话工厂（可以是生产库也可以是测试用内存库）
# 返回值：配置好的 FastAPI 实例
# ─────────────────────────────────────────────
def create_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    # 延迟导入，避免模块循环依赖（logging_config 间接依赖 config，config 不依赖 main）
    from dzmm.logging_config import setup_logging
    setup_logging()  # 初始化日志系统：把所有日志同时写入文件和终端，且只初始化一次

    app = FastAPI(title="dzmm")  # 创建 FastAPI 实例，title 会显示在自动生成的 /docs 页面

    # ── 跨域中间件（CORS）──────────────────────────────────────────────────
    # 问题背景：浏览器的同源策略会阻止网页向「与自身来源不同的域名/端口」发送请求。
    # 本应用是本地桌面应用：前端（Vite 开发服务器跑在 localhost:5173，Tauri webview 是 tauri://）
    # 和后端（uvicorn 跑在 localhost:8765）来源不同，所以需要允许跨域。
    # allow_origins=["*"] 表示接受任意来源的请求（本地应用不需要精细控制）。
    # allow_credentials=False：不允许跨域携带 cookie（本应用不用 cookie 鉴权，避免安全问题）。
    # 注：Vite 的 proxy 虽然也能解决跨域，但它会缓冲 SSE 响应，导致流式输出失效，所以直接开 CORS。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # 允许所有来源
        allow_credentials=False,  # 不允许携带 cookie
        allow_methods=["*"],      # 允许所有 HTTP 方法（GET/POST/PUT/DELETE 等）
        allow_headers=["*"],      # 允许所有请求头
    )

    # ── 请求日志中间件：方便排查前端报错 ────────────────────────────────────
    # uvicorn 的 access log 默认走 stdout，没进入 ~/.dzmm/dzmm.log，
    # 排查"前端报错但日志只看到 LLM 调用"时很难定位。这里记录所有 wizard/
    # sessions 写操作的入站请求和响应状态码到 dzmm.log。
    import logging as _logging
    import time as _time
    _req_log = _logging.getLogger("dzmm.requests")

    @app.middleware("http")
    async def _request_logger(request, call_next):
        path = request.url.path
        # 只记录关键路径，避免 SSE / state 轮询噪音
        interesting = (
            path.startswith("/wizard")
            or path.startswith("/worlds")
            or path.startswith("/characters")
            or path.startswith("/model_configs")
            or (path.startswith("/sessions") and request.method != "GET")
        )
        if not interesting:
            return await call_next(request)
        started = _time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _req_log.exception("%s %s — UNHANDLED EXCEPTION", request.method, path)
            raise
        elapsed_ms = int((_time.perf_counter() - started) * 1000)
        level = _logging.WARNING if response.status_code >= 400 else _logging.INFO
        _req_log.log(
            level,
            "%s %s -> %d (%dms)",
            request.method, path, response.status_code, elapsed_ms,
        )
        return response

    # ── 依赖注入：把「获取数据库会话」的函数注入给各路由 ────────────────────
    # FastAPI 的「依赖注入」机制：路由函数可以声明参数 session: AsyncSession = Depends(get_session_dep)，
    # FastAPI 会自动调用 get_session_dep()，把它的返回值传给路由函数，无需路由函数自己创建数据库连接。
    # 这里用 async with ... yield 的模式，保证每个请求用完数据库会话后自动关闭，不会泄漏连接。
    async def get_session_dep() -> AsyncIterator[AsyncSession]:
        # async with session_maker() as s：打开一个数据库会话（自动处理提交/回滚/关闭）
        # yield s：把会话传给路由函数；路由函数执行完后，with 块负责清理
        async with session_maker() as s:
            yield s

    # 某些路由需要直接拿到 session_maker 本身（例如需要在子任务里自己创建会话），
    # 所以单独提供一个依赖函数，直接返回工厂对象。
    def get_session_maker_dep() -> async_sessionmaker[AsyncSession]:
        return session_maker

    # ── 批量注册「需要数据库」的路由模块 ────────────────────────────────────
    # app.dependency_overrides 是 FastAPI 的「依赖替换」字典：
    # key = 路由模块里声明的「占位依赖函数」，value = 实际要调用的函数。
    # 这样做的好处：各路由模块里的 get_session_dep 只是一个「声明」，
    # 实际使用哪个数据库由这里的 override 决定，测试时可以换成内存库而无需改路由代码。
    for module in (
        routes_worlds,
        routes_characters,
        routes_models,
        routes_sessions,
        routes_screenplay,
        routes_screenplays,
        routes_wizard,
    ):
        # routes_screenplay reuses routes_sessions.get_session_dep (same function
        # object), so the override applied while iterating routes_sessions also
        # covers it. Iterating routes_screenplay just adds an idempotent override
        # by the same key — keeps the loop uniform and resilient if it ever
        # introduces its own dep.
        # getattr(module, "get_session_dep", get_session_dep)：
        #   尝试获取模块自己定义的 get_session_dep；
        #   如果模块没有定义（比如 routes_screenplay 直接复用 routes_sessions 的），
        #   则回退到本文件里刚定义的 get_session_dep，保证 override 键存在。
        dep = getattr(module, "get_session_dep", get_session_dep)
        app.dependency_overrides[dep] = get_session_dep  # 用真正的数据库会话替换占位函数
        app.include_router(module.router)                # 把该模块的所有路由注册到 app 上

    # ── 不需要数据库的路由，直接注册 ────────────────────────────────────────
    # System routes don't need DB session.
    app.include_router(routes_system.router)        # /system/info 等系统信息接口
    app.include_router(routes_system.health_router) # /health 健康检查接口（供 Tauri/运维监控调用）

    # TTS proxy route.
    app.include_router(routes_tts.router)  # /tts/... 文字转语音代理接口，转发给第三方 TTS 服务

    # ── 单独注册「需要数据库但不在上面循环里」的路由 ─────────────────────────
    # Assets CRUD + upload + serve + attach.
    app.dependency_overrides[routes_assets.get_session_dep] = get_session_dep
    app.include_router(routes_assets.router)  # /assets/... 素材管理（上传图片、音频、头像等）

    # Factions API.
    app.dependency_overrides[routes_factions.get_session_dep] = get_session_dep
    app.include_router(routes_factions.router)  # /factions/... 派系增删改查

    # v0.10 T11: Debug "Agents" tab (per-stream prompt + history).
    # 调试用路由，放在应用内部（不对外暴露），用于查看每个 AI Agent 的历史对话和 prompt
    from dzmm.api.routes_debug_agents import (
        router as debug_agents_router,
        get_session_dep as debug_agents_get_session_dep,
    )
    app.dependency_overrides[debug_agents_get_session_dep] = get_session_dep
    app.include_router(debug_agents_router)

    # 让 routes_sessions 里需要 session_maker 的依赖也能拿到正确的工厂实例
    app.dependency_overrides[routes_sessions.get_session_maker_dep] = get_session_maker_dep

    # ── 可选：托管前端静态文件 ──────────────────────────────────────────────
    # If DZMM_FRONTEND_DIST points at a directory of built frontend files,
    # mount it at "/" so a phone on the LAN can fetch the UI from the same
    # backend that serves the API. Mount LAST so API routes win.
    # 如果环境变量 DZMM_FRONTEND_DIST 指向一个已构建的前端目录（npm run build 的输出），
    # 就把整个目录挂载到 "/"，让后端同时充当前端服务器。
    # 「挂载在最后」是关键：FastAPI 路由匹配是按注册顺序来的，先注册的 API 路由优先匹配，
    # 静态文件兜底，避免 /api/xxx 被当成静态文件路径。
    dist = os.environ.get("DZMM_FRONTEND_DIST")
    if dist and Path(dist).is_dir():
        # html=True：未找到对应文件时返回 index.html，支持前端单页应用（SPA）的路由
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


# ─────────────────────────────────────────────
# build_default_app：生产环境真正使用的启动函数
# 负责完整的初始化流程：建库 → 种子数据 → 素材目录 → NPC 记忆系统 → 创建 app
# 是 async 函数，因为数据库初始化是异步 I/O 操作
# ─────────────────────────────────────────────
async def build_default_app() -> FastAPI:
    import logging
    from dzmm.config import APP_DIR               # 用户数据目录（~/.dzmm）
    from dzmm.seed_data import seed_if_empty      # 如果数据库是空的，植入初始世界/角色数据
    from dzmm.service.assets import init_paths as init_asset_paths, seed_builtin_assets  # 素材目录初始化

    log = logging.getLogger(__name__)  # 获取以当前模块名（dzmm.main）命名的 logger，便于日志定位

    engine = get_engine()         # 创建 SQLAlchemy 异步数据库引擎（连接池 + 驱动配置）
    await init_db(engine)         # 对比当前数据库结构和 ORM 模型定义，自动建表/升级（idempotent，可重复调用）
    session_maker = async_session(engine)  # 创建「会话工厂」：每次调用 session_maker() 都会产生一个新的数据库会话
    await seed_if_empty(session_maker)     # 如果数据库里没有任何世界/角色，植入示例数据让用户有东西可玩

    # ── 确定内置素材目录的路径 ────────────────────────────────────────────
    # __file__ 是本文件（main.py）的绝对路径，.resolve() 转成真实路径（解析符号链接）
    # .parent.parent.parent.parent 往上走 4 层目录，到达仓库根目录（repo root）
    # 内置素材放在 packaging/assets/builtin/，随应用打包分发
    _pkg_root = Path(__file__).resolve().parent.parent.parent.parent  # repo root
    builtin_dir = _pkg_root / "packaging" / "assets" / "builtin"
    # 告诉素材服务：用户上传的素材放在 APP_DIR，内置素材在 builtin_dir
    init_asset_paths(APP_DIR, builtin_dir)

    # 初始化 NPC 长期记忆系统（把记忆文件存储目录设置为 APP_DIR 下的子目录）
    from dzmm.service.npc_memory import init_npc_memory
    init_npc_memory(APP_DIR)

    # ── 植入内置素材（幂等操作，已存在则跳过）────────────────────────────────
    # async with session_maker() as _seed_session：打开一个临时数据库会话，用完自动关闭
    async with session_maker() as _seed_session:
        n_seeded = await seed_builtin_assets(_seed_session)  # 把 builtin_dir 里的素材写入数据库
        if n_seeded > 0:
            log.info("seeded %d builtin assets", n_seeded)  # 记录日志，说明本次启动植入了多少条素材

    return create_app(session_maker)  # 所有初始化完成，创建并返回 FastAPI 实例
