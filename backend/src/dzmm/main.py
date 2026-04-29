from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dzmm.api import (
    routes_characters,
    routes_models,
    routes_sessions,
    routes_worlds,
)
from dzmm.db.base import async_session, get_engine, init_db


def create_app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    from dzmm.logging_config import setup_logging
    setup_logging()
    app = FastAPI(title="dzmm")

    async def get_session_dep() -> AsyncIterator[AsyncSession]:
        async with session_maker() as s:
            yield s

    def get_session_maker_dep() -> async_sessionmaker[AsyncSession]:
        return session_maker

    for module in (routes_worlds, routes_characters, routes_models, routes_sessions):
        app.dependency_overrides[module.get_session_dep] = get_session_dep
        app.include_router(module.router)

    app.dependency_overrides[routes_sessions.get_session_maker_dep] = get_session_maker_dep
    return app


async def build_default_app() -> FastAPI:
    engine = get_engine()
    await init_db(engine)
    return create_app(async_session(engine))
