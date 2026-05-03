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

_V11_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [
        ("revealed_json", "revealed_json TEXT NOT NULL DEFAULT '{\"name\": true}'"),
    ],
}

# v0.13.1 — Player feedback table is created via Base.metadata.create_all.
# Nothing to migrate column-wise.

_V025_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("settings_json", "settings_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "npcs": [
        ("current_location", "current_location VARCHAR(120)"),  # nullable, no DEFAULT
    ],
    "locations": [
        ("items_json", "items_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}

_V026_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("doom_score", "doom_score INTEGER NOT NULL DEFAULT 0"),
    ],
}

_V027_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [("last_initiative_turn", "last_initiative_turn INTEGER NOT NULL DEFAULT 0")],
}

_V028_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "screenplays": [
        ("world_id", "world_id INTEGER REFERENCES worlds(id)"),
        ("title", "title VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_name", "pc_name VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_profile_md", "pc_profile_md TEXT NOT NULL DEFAULT ''"),
        ("pc_base_stats_json", "pc_base_stats_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "sessions": [
        ("screenplay_id", "screenplay_id INTEGER REFERENCES screenplays(id)"),
    ],
}

_V029_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [
        ("tts_voice", "tts_voice VARCHAR(120) NOT NULL DEFAULT ''"),
    ],
    "screenplays": [
        ("pc_tts_voice", "pc_tts_voice VARCHAR(120) NOT NULL DEFAULT ''"),
    ],
}

_V030_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("scene_turn_count", "scene_turn_count INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _make_screenplay_session_id_nullable_sync(conn) -> None:
    """v0.2.8: make screenplays.session_id nullable via table rebuild.
    SQLite does not support ALTER COLUMN, so we copy→drop→rename.
    Idempotent: no-op if session_id is already nullable or missing."""
    cols = conn.exec_driver_sql("PRAGMA table_info(screenplays)").fetchall()
    if not cols:
        return  # table doesn't exist yet; create_all will handle it correctly
    session_id_col = next((r for r in cols if r[1] == "session_id"), None)
    if session_id_col is None or session_id_col[3] == 0:
        return  # already nullable

    col_defs = []
    for _cid, name, coltype, notnull, dflt_value, pk in cols:
        parts = [f"{name} {coltype}"]
        if pk:
            parts.append("PRIMARY KEY")
        elif name != "session_id" and notnull:
            parts.append("NOT NULL")
        if dflt_value is not None:
            parts.append(f"DEFAULT {dflt_value}")
        col_defs.append(" ".join(parts))

    col_names = ", ".join(r[1] for r in cols)
    conn.exec_driver_sql(
        f"CREATE TABLE _screenplays_tmp ({', '.join(col_defs)})"
    )
    conn.exec_driver_sql(
        f"INSERT INTO _screenplays_tmp ({col_names}) SELECT {col_names} FROM screenplays"
    )
    conn.exec_driver_sql("DROP TABLE screenplays")
    conn.exec_driver_sql("ALTER TABLE _screenplays_tmp RENAME TO screenplays")


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
        for table, cols in _V11_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V025_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V026_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V027_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        await conn.run_sync(_make_screenplay_session_id_nullable_sync)
        for table, cols in _V028_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V029_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V030_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
