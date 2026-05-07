import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.api import (
    routes_assets,
    routes_characters,
    routes_models,
    routes_screenplay,
    routes_screenplays,
    routes_sessions,
    routes_system,
    routes_tts,
    routes_wizard,
    routes_worlds,
)
from dzmm.db.base import async_session, get_engine, init_db


def create_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    from dzmm.logging_config import setup_logging
    setup_logging()
    app = FastAPI(title="dzmm")

    # Local desktop app — frontend (Vite dev / Tauri webview) is on a
    # different origin from the backend. Allow all so SSE works without
    # the Vite proxy (which buffers SSE responses).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def get_session_dep() -> AsyncIterator[AsyncSession]:
        async with session_maker() as s:
            yield s

    def get_session_maker_dep() -> async_sessionmaker[AsyncSession]:
        return session_maker

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
        dep = getattr(module, "get_session_dep", get_session_dep)
        app.dependency_overrides[dep] = get_session_dep
        app.include_router(module.router)

    # System routes don't need DB session.
    app.include_router(routes_system.router)
    app.include_router(routes_system.health_router)

    # TTS proxy route.
    app.include_router(routes_tts.router)

    # Assets CRUD + upload + serve + attach.
    app.dependency_overrides[routes_assets.get_session_dep] = get_session_dep
    app.include_router(routes_assets.router)

    app.dependency_overrides[routes_sessions.get_session_maker_dep] = get_session_maker_dep

    # If DZMM_FRONTEND_DIST points at a directory of built frontend files,
    # mount it at "/" so a phone on the LAN can fetch the UI from the same
    # backend that serves the API. Mount LAST so API routes win.
    dist = os.environ.get("DZMM_FRONTEND_DIST")
    if dist and Path(dist).is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


async def build_default_app() -> FastAPI:
    import logging
    from dzmm.config import APP_DIR
    from dzmm.seed_data import seed_if_empty
    from dzmm.service.assets import init_paths as init_asset_paths, seed_builtin_assets

    log = logging.getLogger(__name__)

    engine = get_engine()
    await init_db(engine)
    session_maker = async_session(engine)
    await seed_if_empty(session_maker)

    # Resolve builtin assets dir (next to repo packaging/)
    _pkg_root = Path(__file__).resolve().parent.parent.parent.parent  # repo root
    builtin_dir = _pkg_root / "packaging" / "assets" / "builtin"
    init_asset_paths(APP_DIR, builtin_dir)

    from dzmm.service.npc_memory import init_npc_memory
    init_npc_memory(APP_DIR)

    async with session_maker() as _seed_session:
        n_seeded = await seed_builtin_assets(_seed_session)
        if n_seeded > 0:
            log.info("seeded %d builtin assets", n_seeded)

    return create_app(session_maker)
