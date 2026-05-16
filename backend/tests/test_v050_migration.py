"""Test that _V050_MIGRATIONS columns are created on a fresh in-memory DB."""

import pytest

from dzmm.db.base import get_engine, init_db


@pytest.fixture
async def fresh_engine():
    engine = get_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


# run_sync requires a plain synchronous callable (not async)
def _get_columns_sync(conn, table: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


async def test_v050_character_columns(fresh_engine):
    async with fresh_engine.begin() as conn:
        cols = await conn.run_sync(_get_columns_sync, "characters")

    expected = {
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma",
        "max_hp", "max_sanity", "max_stamina",
        "skills_json", "inventory_json", "equipment_json",
    }
    for col in expected:
        assert col in cols, f"Missing column 'characters.{col}'"


async def test_v050_npc_stat_block_json(fresh_engine):
    async with fresh_engine.begin() as conn:
        cols = await conn.run_sync(_get_columns_sync, "npcs")
    assert "stat_block_json" in cols


async def test_v050_char_states_stamina(fresh_engine):
    async with fresh_engine.begin() as conn:
        cols = await conn.run_sync(_get_columns_sync, "char_states")
    assert "stamina" in cols


async def test_v050_session_ruleset_version(fresh_engine):
    async with fresh_engine.begin() as conn:
        cols = await conn.run_sync(_get_columns_sync, "sessions")
    assert "ruleset_version" in cols
