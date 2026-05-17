"""Tests for v0.54: legacy mechanic tag rejection and GM warning injection.

Tests:
  - test_state_change_hp_negative_blocked_and_warned
  - test_state_change_hp_positive_still_applied
  - test_state_change_sanity_negative_still_applied (narrative ok)
  - test_dice_tag_warning_recorded
  - test_warnings_injected_into_key_facts_block
  - test_warnings_drained_after_render
  - test_warnings_capped_at_5
  - test_legacy_dice_d20_extraction_still_works_for_stuck_detection
  - test_negative_hp_no_warning_when_zero_hp (delta=0 isn't damage)
  - test_v054_mechanic_warnings_json_column
"""

import json

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    Session as GameSession,
    World,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply import apply_tags
from dzmm.service.state_apply.dice_monitor import extract_d20_value
from dzmm.service.game import _build_key_facts


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session(tmp_path):
    """Yield (SQLAlchemy AsyncSession, session_id) with a minimal game state."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/lr_test.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark", rules_json='{"mode":"light"}')
        char = Character(
            world=world,
            name="TestPC",
            profile_md="hero",
            base_stats_json='{"hp":20,"sanity":15,"stamina":20}',
        )
        cfg = ModelConfig(
            name="m",
            type="ollama",
            base_url="http://localhost:11434",
            model_name="qwen",
        )
        s.add_all([world, char, cfg])
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
        s.add(
            CharState(
                session_id=sess.id,
                stats_json='{"hp":20,"sanity":15,"stamina":20}',
                inventory_json="[]",
            )
        )
        await s.commit()
        yield s, sess.id
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_stats(s, sid: int) -> dict:
    cs = (
        await s.execute(select(CharState).where(CharState.session_id == sid))
    ).scalar_one()
    return json.loads(cs.stats_json)


async def _get_session(s, sid: int) -> GameSession:
    return await s.get(GameSession, sid)


async def _get_mechanic_warnings(s, sid: int) -> list:
    sess = await _get_session(s, sid)
    raw = getattr(sess, "mechanic_warnings_json", None) or "[]"
    return json.loads(raw)


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_state_change_hp_negative_blocked_and_warned(db_session):
    """<state_change hp="-5"/> must NOT reduce HP and must record a warning."""
    s, sid = db_session
    tag = TagComplete(name="state_change", content='{"hp": -5}')
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    stats = await _get_stats(s, sid)
    assert stats["hp"] == 20, "HP must be unchanged when a negative delta is rejected"

    warnings = await _get_mechanic_warnings(s, sid)
    assert len(warnings) == 1
    w = warnings[0]
    assert w["kind"] == "rejected_damage"
    assert w["tag"] == "state_change"
    assert w["attempted"]["hp"] == -5
    assert w["turn"] == 2
    assert "attack" in w["reason"] or "dice_request" in w["reason"]


async def test_state_change_hp_positive_still_applied(db_session):
    """<state_change hp="+3"/> (healing) must still increase HP."""
    s, sid = db_session
    tag = TagComplete(name="state_change", content='{"hp": 3}')
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    stats = await _get_stats(s, sid)
    assert stats["hp"] == 23, "Positive HP delta (healing) must be applied"

    warnings = await _get_mechanic_warnings(s, sid)
    assert warnings == [], "No warning should be recorded for positive HP delta"


async def test_state_change_sanity_negative_still_applied(db_session):
    """<state_change sanity="-3"/> (narrative decay) must still reduce sanity."""
    s, sid = db_session
    tag = TagComplete(name="state_change", content='{"sanity": -3}')
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    stats = await _get_stats(s, sid)
    assert stats["sanity"] == 12, "Negative sanity delta must be applied (narrative case)"

    warnings = await _get_mechanic_warnings(s, sid)
    assert warnings == [], "No warning for narrative sanity decay"


async def test_dice_tag_warning_recorded(db_session):
    """Legacy <dice> tag must trigger a mechanic warning (kind='rejected_dice')."""
    s, sid = db_session
    tag = TagComplete(name="dice", attrs={"pc_roll": "12", "dc": "15", "outcome": "失败"}, content="d20=12，失败")
    await apply_tags(s, sid, current_turn=3, tags=[tag])
    await s.commit()

    warnings = await _get_mechanic_warnings(s, sid)
    assert len(warnings) == 1
    w = warnings[0]
    assert w["kind"] == "rejected_dice"
    assert w["tag"] == "dice"
    assert w["turn"] == 3
    assert "skill_request" in w["reason"] or "dice_request" in w["reason"]


async def test_warnings_injected_into_key_facts_block(db_session):
    """Warnings recorded in turn N should appear in _build_key_facts called for turn N+1."""
    s, sid = db_session

    # Emit a rejected HP delta in turn 5
    tag = TagComplete(name="state_change", content='{"hp": -7}')
    await apply_tags(s, sid, current_turn=5, tags=[tag])
    await s.commit()

    char = (await s.execute(select(Character))).scalar_one()
    key_facts = await _build_key_facts(s, sid, current_turn=6, character=char)

    assert "⚠️" in key_facts, "Key facts must contain the warning block"
    assert "state_change" in key_facts or "hp" in key_facts.lower() or "attack" in key_facts
    assert "上回合标签使用警告" in key_facts


async def test_warnings_drained_after_render(db_session):
    """After _build_key_facts renders warnings, they must be cleared for that turn."""
    s, sid = db_session

    # Record a warning in turn 7
    tag = TagComplete(name="state_change", content='{"hp": -3}')
    await apply_tags(s, sid, current_turn=7, tags=[tag])
    await s.commit()

    char = (await s.execute(select(Character))).scalar_one()
    # Render for turn 8 (reads warnings from turn 7)
    await _build_key_facts(s, sid, current_turn=8, character=char)
    await s.commit()

    # Now render for turn 9 — turn-7 warnings should be gone
    key_facts2 = await _build_key_facts(s, sid, current_turn=9, character=char)
    assert "上回合标签使用警告" not in key_facts2, "Drained warnings must not reappear next turn"


async def test_warnings_capped_at_5(db_session):
    """Even if 7 warnings are recorded for a turn, key_facts should show at most 5."""
    s, sid = db_session

    # Inject 7 warnings manually into the session
    sess = await _get_session(s, sid)
    warnings_7 = [
        {
            "turn": 10,
            "kind": "rejected_damage",
            "tag": "state_change",
            "attempted": {"hp": -i},
            "reason": "战斗伤害走 <attack> 或 <dice_request>，<state_change hp=-N> 已禁用",
        }
        for i in range(1, 8)
    ]
    sess.mechanic_warnings_json = json.dumps(warnings_7, ensure_ascii=False)
    await s.commit()

    char = (await s.execute(select(Character))).scalar_one()
    key_facts = await _build_key_facts(s, sid, current_turn=11, character=char)

    # Count how many warning bullet points appear (each starts with "- 你用了")
    bullet_count = key_facts.count("你用了 <state_change")
    assert bullet_count <= 5, f"Expected at most 5 warning bullets, got {bullet_count}"


async def test_legacy_dice_d20_extraction_still_works_for_stuck_detection(db_session):
    """dice_monitor.extract_d20_value must still parse d20 values for stuck detection."""
    # This test does NOT use apply_tags — it tests dice_monitor directly to ensure
    # the detection side is not regressed.
    assert extract_d20_value("d20=9，失败") == 9
    assert extract_d20_value("D20=15 成功") == 15
    assert extract_d20_value("no dice here") is None
    assert extract_d20_value("d20=0") is None   # out of 1-20 range
    assert extract_d20_value("d20=21") is None  # out of 1-20 range


async def test_negative_hp_no_warning_when_zero_delta(db_session):
    """A delta of 0 for hp must be applied (or no-op) without generating a warning."""
    s, sid = db_session
    tag = TagComplete(name="state_change", content='{"hp": 0}')
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    stats = await _get_stats(s, sid)
    assert stats["hp"] == 20, "Zero delta must not change HP"

    warnings = await _get_mechanic_warnings(s, sid)
    assert warnings == [], "Zero HP delta must not generate a warning"


async def test_v054_mechanic_warnings_json_column(db_session):
    """Session.mechanic_warnings_json column must exist and default to '[]'."""
    s, sid = db_session
    sess = await _get_session(s, sid)
    raw = getattr(sess, "mechanic_warnings_json", None)
    assert raw is not None, "mechanic_warnings_json column must exist on Session"
    parsed = json.loads(raw)
    assert parsed == [], "Default value must be an empty list"
