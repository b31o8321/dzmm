"""Tests for engine/character.py level_up() function (v0.15.2 B3)."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import Character, CharState, ModelConfig, Session as GameSession, World
from dzmm.engine.character import level_up
from dzmm.service.state_apply.character_xp import _apply_character_xp


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/levelup_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_char(
    s: AsyncSession,
    *,
    xp: int = 0,
    level: int = 1,
    skills: dict | None = None,
    strength: int = 10,
    dexterity: int = 10,
    constitution: int = 10,
    intelligence: int = 12,
    wisdom: int = 8,
    charisma: int = 10,
) -> tuple[Character, GameSession]:
    world = World(name="W", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    char = Character(
        world_id=world.id,
        name="PC",
        profile_md="x",
        base_stats_json="{}",
        xp=xp,
        level=level,
        skills_json=json.dumps(skills or {}, ensure_ascii=False),
        strength=strength,
        dexterity=dexterity,
        constitution=constitution,
        intelligence=intelligence,
        wisdom=wisdom,
        charisma=charisma,
        max_hp=30,
        max_sanity=50,
        max_stamina=30,
    )
    s.add(char)
    cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost", model_name="t")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="run",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    s.add(sess)
    await s.flush()

    state = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": 20, "sanity": 40}),
        stamina=20,
    )
    s.add(state)
    await s.commit()
    return char, sess


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_level_up_when_xp_threshold_met(db):
    """100 XP at level 1 → should level up to 2."""
    char, _ = await _make_char(db, xp=100, level=1)
    result = await level_up(db, char.id)
    assert result is not None
    assert result["level"] == 2
    await db.refresh(char)
    assert char.level == 2


async def test_level_up_no_op_when_below_threshold(db):
    """99 XP at level 1 → not enough; returns None."""
    char, _ = await _make_char(db, xp=99, level=1)
    result = await level_up(db, char.id)
    assert result is None
    await db.refresh(char)
    assert char.level == 1


async def test_level_up_multiple_levels_at_once_xp_300(db):
    """Level 1 with 300 XP: level 1 needs 100 (→ lv2), lv2 needs 200 (→ lv3?).

    Required XP per level: level * 100.
    Level 1 → 2: needs 100 XP → 300-100=200 remaining
    Level 2 → 3: needs 200 XP → 200-200=0 remaining
    So character goes from level 1 → level 3 with exactly 300 XP.
    """
    char, _ = await _make_char(db, xp=300, level=1)
    result = await level_up(db, char.id)
    assert result is not None
    await db.refresh(char)
    assert char.level == 3
    assert char.xp == 0


async def test_level_up_picks_attribute_matching_top_skill(db):
    """Top skill '潜行' (dexterity) → dexterity should be raised."""
    char, _ = await _make_char(db, xp=100, level=1, skills={"潜行": 60, "推理": 30})
    result = await level_up(db, char.id)
    assert result is not None
    assert result["attribute_raised"] == "dexterity"
    assert result["skill_raised"] == "潜行"


async def test_level_up_skill_capped_at_100(db):
    """A skill already at 98 + 5 = 103 → should be capped at 100."""
    char, _ = await _make_char(db, xp=100, level=1, skills={"潜行": 98})
    await level_up(db, char.id)
    await db.refresh(char)
    skills = json.loads(char.skills_json)
    assert skills["潜行"] == 100


async def test_level_up_no_skills_picks_highest_attribute(db):
    """No skills → pick the attribute with the highest value (ties broken by name)."""
    # wisdom=15 is highest; should be raised
    char, _ = await _make_char(
        db, xp=100, level=1, skills={},
        strength=10, dexterity=10, constitution=10,
        intelligence=10, wisdom=15, charisma=10,
    )
    result = await level_up(db, char.id)
    assert result is not None
    assert result["attribute_raised"] == "wisdom"


async def test_level_up_returns_change_summary(db):
    """Return dict should have level, attribute_raised, skill_raised keys."""
    char, _ = await _make_char(db, xp=100, level=1, skills={"调查": 50})
    result = await level_up(db, char.id)
    assert result is not None
    assert "level" in result
    assert "attribute_raised" in result
    assert "skill_raised" in result
    assert result["skill_raised"] == "调查"
    assert result["attribute_raised"] == "wisdom"


async def test_level_up_idempotent_when_called_twice(db):
    """Calling level_up twice without earning more XP should not double-level."""
    char, _ = await _make_char(db, xp=100, level=1)
    await level_up(db, char.id)
    await db.refresh(char)
    assert char.level == 2
    # Second call — no new XP earned
    result2 = await level_up(db, char.id)
    assert result2 is None
    await db.refresh(char)
    assert char.level == 2


async def test_apply_character_xp_triggers_level_up(db):
    """_apply_character_xp with delta=100 at level 1 should auto-level-up."""
    char, sess = await _make_char(db, xp=0, level=1)
    await _apply_character_xp(db, sess.id, {"delta": "100"}, "")
    await db.refresh(char)
    assert char.level == 2
    # XP should be fully consumed (0 left after spending 100 for level 1→2)
    assert char.xp == 0


async def test_level_up_stores_pending_announcement(db):
    """level_up should write level_up_pending_json on the Character row."""
    char, _ = await _make_char(db, xp=100, level=1, skills={"推理": 40})
    await level_up(db, char.id)
    await db.refresh(char)
    pending_raw = char.level_up_pending_json
    assert pending_raw  # not empty
    pending = json.loads(pending_raw)
    assert pending["old_level"] == 1
    assert pending["new_level"] == 2
    assert pending["attribute_raised"] == "intelligence"
    assert pending["skill_raised"] == "推理"


async def test_key_facts_shows_level_up_announcement(db):
    """_build_key_facts should inject level-up block and drain pending_json."""
    from dzmm.service.game import _build_key_facts

    char, sess = await _make_char(db, xp=100, level=1, skills={"调查": 45})
    await level_up(db, char.id)
    await db.refresh(char)
    # Confirm pending is set
    assert char.level_up_pending_json

    key_facts = await _build_key_facts(db, sess.id, current_turn=2, character=char)
    # Announcement block should appear
    assert "升级" in key_facts or "角色升级" in key_facts
    assert "调查" in key_facts

    # After _build_key_facts, the pending announcement is drained
    await db.refresh(char)
    assert char.level_up_pending_json == ""
