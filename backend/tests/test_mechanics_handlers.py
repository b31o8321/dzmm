"""Tests for service/state_apply/mechanics.py — v0.15 Batch 2 handlers.

Tests:
  _apply_dice_request: deterministic with seeded rng, writes pending_resolutions,
                       rejects malformed formula
  _apply_skill_request: success/failure/crit-success/crit-fail, unknown skill
                        defaults skill_level=0, unknown attribute → silent skip
  _apply_item_use: success applies heal via apply_vital_delta, missing item
                   logs warning + records "missing" resolution, consumable removes
                   from inventory, pending_resolutions_json caps at 100 entries
"""

import json
import random
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    Session as GameSession,
    World,
)
from dzmm.engine.schema import Item, ItemEffect
from dzmm.service.state_apply.mechanics import (
    _apply_dice_request,
    _apply_skill_request,
    _apply_item_use,
    _MAX_PENDING_RESOLUTIONS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/mech_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_scenario(
    s: AsyncSession,
    *,
    hp: int = 20,
    max_hp: int = 30,
    inventory_items: list[Item] | None = None,
    dexterity: int = 14,
    skills: dict | None = None,
):
    """Create a minimal World / Character / CharState / Session setup."""
    world = World(name="W", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    inv_json = json.dumps(
        [i.model_dump() for i in (inventory_items or [])]
    )
    skills_json = json.dumps(skills or {})

    char = Character(
        world_id=world.id,
        name="PC",
        profile_md="x",
        base_stats_json="{}",
        max_hp=max_hp,
        max_sanity=50,
        max_stamina=30,
        inventory_json=inv_json,
        dexterity=dexterity,
        skills_json=skills_json,
    )
    s.add(char)

    cfg = ModelConfig(
        name="m", type="ollama", base_url="http://localhost", model_name="test"
    )
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
        stats_json=json.dumps({"hp": hp, "sanity": 40}),
        stamina=20,
    )
    s.add(state)
    await s.commit()
    return char, sess, state


def _healing_potion(qty: int = 1) -> Item:
    return Item(
        name="治疗药水",
        qty=qty,
        item_type="consumable",
        effects=[ItemEffect(type="heal_hp", amount=15)],
    )


def _load_resolutions(sess: GameSession) -> list[dict]:
    try:
        return json.loads(sess.pending_resolutions_json or "[]")
    except (TypeError, ValueError):
        return []


# ── _apply_dice_request ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dice_request_rolls_and_records(db):
    """Rolls are deterministic with a seeded rng and the result is persisted."""
    char, sess, state = await _make_scenario(db)
    session_id = sess.id

    # Patch roll() to use a seeded RNG for determinism
    seeded_rng = random.Random(42)
    with patch("dzmm.service.state_apply.mechanics.roll") as mock_roll:
        from dzmm.engine.dice import DiceResult
        # Simulate roll("2d6+3") with the seeded rng
        from dzmm.engine.dice import roll as real_roll
        real_result = real_roll("2d6+3", rng=seeded_rng)
        mock_roll.return_value = real_result

        result = await _apply_dice_request(
            db,
            session_id,
            {"formula": "2d6+3", "purpose": "伤害"},
            current_turn=3,
        )

    assert result is not None
    assert result["formula"] == "2d6+3"
    assert result["purpose"] == "伤害"
    assert isinstance(result["total"], int)
    assert result["modifier"] == 3

    # The handler mutates the Session object in-place via the SQLAlchemy
    # identity map (same session → same Python object). Flush to ensure
    # the write is registered, then read directly without refresh.
    await db.flush()
    records = _load_resolutions(sess)
    assert len(records) == 1
    rec = records[0]
    assert rec["turn"] == 3
    assert rec["kind"] == "dice"
    assert rec["input"]["formula"] == "2d6+3"
    assert "rolls" in rec["result"]


@pytest.mark.asyncio
async def test_dice_request_rejects_malformed_formula(db):
    """Malformed formula returns None and records nothing."""
    char, sess, state = await _make_scenario(db)
    session_id = sess.id

    result = await _apply_dice_request(
        db,
        session_id,
        {"formula": "not-a-formula", "purpose": "test"},
        current_turn=1,
    )
    assert result is None

    await db.refresh(sess)
    records = _load_resolutions(sess)
    assert records == []


@pytest.mark.asyncio
async def test_dice_request_missing_formula_returns_none(db):
    """Missing formula attr returns None gracefully."""
    char, sess, state = await _make_scenario(db)

    result = await _apply_dice_request(
        db, sess.id, {}, current_turn=1
    )
    assert result is None


# ── _apply_skill_request ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_request_success_path(db):
    """High dexterity + matching skill gives succeed result."""
    char, sess, state = await _make_scenario(
        db, dexterity=18, skills={"潜行": 5}
    )

    with patch("dzmm.engine.dice._MODULE_RNG") as mock_rng:
        mock_rng.randint.return_value = 15  # d20=15

        result = await _apply_skill_request(
            db,
            sess.id,
            {"skill": "潜行", "attribute": "dexterity", "dc": "12"},
            current_turn=2,
        )

    assert result is not None
    assert result["succeeded"] is True
    assert result["skill"] == "潜行"
    assert result["attribute"] == "dexterity"

    await db.flush()
    records = _load_resolutions(sess)
    assert len(records) == 1
    assert records[0]["kind"] == "skill"


@pytest.mark.asyncio
async def test_skill_request_failure_path(db):
    """Low roll gives failed result."""
    char, sess, state = await _make_scenario(
        db, dexterity=8, skills={}
    )

    with patch("dzmm.engine.dice._MODULE_RNG") as mock_rng:
        mock_rng.randint.return_value = 2  # d20=2; total=2-1=1 < dc=14

        result = await _apply_skill_request(
            db,
            sess.id,
            {"skill": "潜行", "attribute": "dexterity", "dc": "14"},
            current_turn=2,
        )

    assert result is not None
    assert result["succeeded"] is False


@pytest.mark.asyncio
async def test_skill_request_crit_success(db):
    """Natural 20 → crit=True, succeeded=True."""
    char, sess, state = await _make_scenario(db, dexterity=10)

    with patch("dzmm.engine.dice._MODULE_RNG") as mock_rng:
        mock_rng.randint.return_value = 20

        result = await _apply_skill_request(
            db,
            sess.id,
            {"skill": "知觉", "attribute": "wisdom", "dc": "10"},
            current_turn=1,
        )

    assert result is not None
    assert result["crit"] is True
    assert result["succeeded"] is True


@pytest.mark.asyncio
async def test_skill_request_crit_fail(db):
    """Natural 1 → crit=True, succeeded=False."""
    char, sess, state = await _make_scenario(db, dexterity=10)

    with patch("dzmm.engine.dice._MODULE_RNG") as mock_rng:
        mock_rng.randint.return_value = 1

        result = await _apply_skill_request(
            db,
            sess.id,
            {"skill": "知觉", "attribute": "wisdom", "dc": "5"},
            current_turn=1,
        )

    assert result is not None
    assert result["crit"] is True
    assert result["succeeded"] is False


@pytest.mark.asyncio
async def test_skill_request_unknown_skill_defaults_to_zero(db):
    """An unknown skill defaults to skill_level=0 without raising."""
    char, sess, state = await _make_scenario(db, skills={})

    with patch("dzmm.engine.dice._MODULE_RNG") as mock_rng:
        mock_rng.randint.return_value = 10

        result = await _apply_skill_request(
            db,
            sess.id,
            {"skill": "不存在技能XYZ", "attribute": "strength", "dc": "8"},
            current_turn=1,
        )

    assert result is not None
    assert result["skill_level"] == 0


@pytest.mark.asyncio
async def test_skill_request_unknown_attribute_silent_skip(db):
    """Unknown attribute → returns None, records warning in pending_resolutions."""
    char, sess, state = await _make_scenario(db)

    result = await _apply_skill_request(
        db,
        sess.id,
        {"skill": "潜行", "attribute": "charismagic", "dc": "12"},
        current_turn=5,
    )

    assert result is None
    await db.flush()
    records = _load_resolutions(sess)
    assert len(records) == 1
    assert "error" in records[0]["result"]


# ── _apply_item_use ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_item_use_success_applies_heal(db):
    """Successful item use applies heal via apply_vital_delta."""
    char, sess, state = await _make_scenario(
        db, hp=10, inventory_items=[_healing_potion(qty=2)]
    )

    result = await _apply_item_use(
        db,
        sess.id,
        {"item_name": "治疗药水"},
        current_turn=3,
    )

    assert result is not None
    assert any(e["type"] == "heal_hp" for e in result["applied_effects"])

    # CharState HP should have increased; apply_vital_delta flushes the session
    # so state.stats_json is already updated in-place on the same identity.
    await db.flush()
    stats = json.loads(state.stats_json)
    assert stats["hp"] > 10  # was 10, now 10 + 15 = 25 (clamped at max_hp=30)


@pytest.mark.asyncio
async def test_item_use_missing_item_logs_warning(db):
    """Missing item records a 'missing' resolution and returns None."""
    char, sess, state = await _make_scenario(db, inventory_items=[])

    result = await _apply_item_use(
        db,
        sess.id,
        {"item_name": "万能钥匙"},
        current_turn=4,
    )

    assert result is None
    await db.flush()
    records = _load_resolutions(sess)
    assert len(records) == 1
    assert records[0]["result"]["missing"] is True
    assert "万能钥匙" in records[0]["result"]["warning"]


@pytest.mark.asyncio
async def test_item_use_consumable_removes_from_inventory(db):
    """Consumable with qty=1 is removed from inventory after use."""
    char, sess, state = await _make_scenario(
        db, inventory_items=[_healing_potion(qty=1)]
    )

    result = await _apply_item_use(
        db,
        sess.id,
        {"item_name": "治疗药水"},
        current_turn=1,
    )

    assert result is not None
    assert result["removed_from_inventory"] is True

    # _save_inventory calls s.flush(), so char.inventory_json is updated in-place
    await db.flush()
    inv = json.loads(char.inventory_json)
    assert len(inv) == 0


@pytest.mark.asyncio
async def test_item_use_multi_qty_decrements_not_removes(db):
    """Consumable with qty=3 loses 1 qty but is not removed."""
    char, sess, state = await _make_scenario(
        db, inventory_items=[_healing_potion(qty=3)]
    )

    result = await _apply_item_use(
        db,
        sess.id,
        {"item_name": "治疗药水"},
        current_turn=1,
    )

    assert result is not None
    assert result["removed_from_inventory"] is False

    await db.flush()
    inv = json.loads(char.inventory_json)
    assert len(inv) == 1
    assert inv[0]["qty"] == 2


# ── pending_resolutions_json cap ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_resolutions_capped_at_max(db):
    """After many appends, pending_resolutions_json never exceeds _MAX_PENDING_RESOLUTIONS."""
    char, sess, state = await _make_scenario(db)

    # Write _MAX_PENDING_RESOLUTIONS + 10 records by calling dice_request many times
    for i in range(_MAX_PENDING_RESOLUTIONS + 10):
        await _apply_dice_request(
            db,
            sess.id,
            {"formula": "d6", "purpose": f"test_{i}"},
            current_turn=i,
        )

    await db.flush()
    records = _load_resolutions(sess)
    assert len(records) <= _MAX_PENDING_RESOLUTIONS
