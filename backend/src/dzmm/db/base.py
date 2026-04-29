from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from dzmm.config import DEFAULT_DB_URL


class Base(DeclarativeBase):
    pass


def get_engine(url: str = DEFAULT_DB_URL) -> AsyncEngine:
    return create_async_engine(url, echo=False, future=True)


def async_session(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    from dzmm.db import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
