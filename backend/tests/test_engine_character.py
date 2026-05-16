"""Tests for engine/character.py — load_character_stats, load_character_skills,
apply_vital_delta, get_skill_check_modifiers."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import Character, CharState, ModelConfig, Session as GameSession, World
from dzmm.engine.character import (
    apply_vital_delta,
    get_skill_check_modifiers,
    load_character_inventory,
    load_character_skills,
    load_character_stats,
)
from dzmm.engine.schema import StatBlock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/char_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_world_char_session(s: AsyncSession):
    """Helper: create World, Character, ModelConfig, Session, CharState."""
    world = World(name="Test World", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    char = Character(
        world_id=world.id,
        name="Hero",
        profile_md="A brave soul",
        base_stats_json="{}",
        strength=14,
        dexterity=12,
        constitution=10,
        intelligence=16,
        wisdom=8,
        charisma=10,
        max_hp=40,
        max_sanity=60,
        max_stamina=35,
        skills_json='{"Dodge": 50, "Stealth": 30}',
        inventory_json='[{"name": "Potion", "qty": 3, "item_type": "consumable", "effects": [{"type": "heal_hp", "amount": 10}]}]',
    )
    s.add(char)

    cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost", model_name="test")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="Run1",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    s.add(sess)
    await s.flush()

    state = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": 40, "sanity": 60}),
        stamina=35,
    )
    s.add(state)
    await s.commit()
    return char, sess, state


# ── load_character_stats ──────────────────────────────────────────────────────

async def test_load_character_stats_round_trip(db):
    char, sess, state = await _make_world_char_session(db)
    sb = await load_character_stats(db, char.id)

    assert isinstance(sb, StatBlock)
    assert sb.strength == 14
    assert sb.dexterity == 12
    assert sb.intelligence == 16
    assert sb.max_hp == 40
    assert sb.max_sanity == 60
    assert sb.max_stamina == 35


async def test_load_character_stats_not_found(db):
    with pytest.raises(ValueError, match="not found"):
        await load_character_stats(db, 9999)


# ── load_character_skills ─────────────────────────────────────────────────────

async def test_load_character_skills_parses_dict(db):
    char, _, _ = await _make_world_char_session(db)
    skills = await load_character_skills(db, char.id)
    assert skills == {"Dodge": 50, "Stealth": 30}


async def test_load_character_skills_fallback_on_malformed(db):
    char, _, _ = await _make_world_char_session(db)
    char.skills_json = "not valid json"
    await db.flush()
    skills = await load_character_skills(db, char.id)
    assert skills == {}


async def test_load_character_skills_empty(db):
    char, _, _ = await _make_world_char_session(db)
    char.skills_json = "{}"
    await db.flush()
    assert await load_character_skills(db, char.id) == {}


# ── load_character_inventory ──────────────────────────────────────────────────

async def test_load_character_inventory(db):
    char, _, _ = await _make_world_char_session(db)
    items = await load_character_inventory(db, char.id)
    assert len(items) == 1
    assert items[0].name == "Potion"
    assert items[0].qty == 3


# ── apply_vital_delta ─────────────────────────────────────────────────────────

async def test_apply_vital_delta_basic(db):
    char, sess, state = await _make_world_char_session(db)
    result = await apply_vital_delta(db, sess.id, char.id, hp=-10)
    assert result["hp"] == 30
    assert result["sanity"] == 60
    assert result["stamina"] == 35


async def test_apply_vital_delta_clamps_to_zero(db):
    char, sess, state = await _make_world_char_session(db)
    result = await apply_vital_delta(db, sess.id, char.id, hp=-9999)
    assert result["hp"] == 0


async def test_apply_vital_delta_clamps_to_max(db):
    char, sess, state = await _make_world_char_session(db)
    # Start from 0 HP, then heal beyond max
    state.stats_json = json.dumps({"hp": 0, "sanity": 60})
    await db.flush()
    result = await apply_vital_delta(db, sess.id, char.id, hp=9999)
    assert result["hp"] == char.max_hp


async def test_apply_vital_delta_stamina_clamp(db):
    char, sess, state = await _make_world_char_session(db)
    result = await apply_vital_delta(db, sess.id, char.id, stamina=-9999)
    assert result["stamina"] == 0


async def test_apply_vital_delta_returns_all_vitals(db):
    char, sess, state = await _make_world_char_session(db)
    result = await apply_vital_delta(db, sess.id, char.id, hp=-5, sanity=-10, stamina=-8)
    assert set(result.keys()) == {"hp", "sanity", "stamina"}
    assert result["hp"] == 35
    assert result["sanity"] == 50
    assert result["stamina"] == 27


# ── get_skill_check_modifiers ─────────────────────────────────────────────────

async def test_get_skill_check_modifiers_correct_tuple(db):
    char, _, _ = await _make_world_char_session(db)
    attr_val, skill_lvl = await get_skill_check_modifiers(db, char.id, "Dodge", "dexterity")
    assert attr_val == 12
    assert skill_lvl == 50


async def test_get_skill_check_modifiers_missing_skill_defaults_to_zero(db):
    char, _, _ = await _make_world_char_session(db)
    attr_val, skill_lvl = await get_skill_check_modifiers(db, char.id, "Swimming", "strength")
    assert attr_val == 14
    assert skill_lvl == 0


async def test_get_skill_check_modifiers_invalid_attribute(db):
    char, _, _ = await _make_world_char_session(db)
    with pytest.raises(ValueError, match="Unknown attribute"):
        await get_skill_check_modifiers(db, char.id, "Dodge", "luck")
