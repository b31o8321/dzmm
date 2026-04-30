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


_V07_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    # table → list of (column_name, full_DDL_fragment)
    "characters": [
        ("portrait_path", "portrait_path VARCHAR(255) NOT NULL DEFAULT ''"),
        ("xp", "xp INTEGER NOT NULL DEFAULT 0"),
        ("level", "level INTEGER NOT NULL DEFAULT 1"),
    ],
    "sessions": [
        ("recall_pending_json", "recall_pending_json TEXT NOT NULL DEFAULT '[]'"),
    ],
    "npcs": [
        ("purpose", "purpose TEXT NOT NULL DEFAULT ''"),
        ("archetype", "archetype VARCHAR(120) NOT NULL DEFAULT ''"),
        ("affinity_json", "affinity_json TEXT NOT NULL DEFAULT '{}'"),
        ("pinned", "pinned BOOLEAN NOT NULL DEFAULT 0"),
        ("emotion_json", "emotion_json TEXT NOT NULL DEFAULT '{}'"),
    ],
}

_V09_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("pc_mood_json", "pc_mood_json TEXT NOT NULL DEFAULT '{}'"),
    ],
}

_V10_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("events_json", "events_json TEXT NOT NULL DEFAULT '[]'"),
        ("parts_json", "parts_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}


def _add_missing_columns_sync(conn, table: str, columns: list[tuple[str, str]]) -> None:
    """SQLite-friendly column-add migration. Idempotent: skips columns that
    already exist. Called from a sync run_sync() context inside init_db()."""
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    existing = {r[1] for r in rows}
    for name, ddl in columns:
        if name not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


async def init_db(engine: AsyncEngine) -> None:
    from dzmm.db import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight column-add migrations for v0.7 features layered on
        # databases originally created at v0.6 or earlier. New columns
        # have safe defaults so existing data is preserved.
        for table, cols in _V07_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V09_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V10_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
