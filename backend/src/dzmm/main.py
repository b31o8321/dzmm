import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.api import (
    routes_characters,
    routes_models,
    routes_screenplay,
    routes_sessions,
    routes_system,
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

    app.dependency_overrides[routes_sessions.get_session_maker_dep] = get_session_maker_dep

    # If DZMM_FRONTEND_DIST points at a directory of built frontend files,
    # mount it at "/" so a phone on the LAN can fetch the UI from the same
    # backend that serves the API. Mount LAST so API routes win.
    dist = os.environ.get("DZMM_FRONTEND_DIST")
    if dist and Path(dist).is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


async def build_default_app() -> FastAPI:
    from dzmm.seed_data import seed_if_empty

    engine = get_engine()
    await init_db(engine)
    session_maker = async_session(engine)
    await seed_if_empty(session_maker)
    return create_app(session_maker)
