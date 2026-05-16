"""Tests for v0.15 Batch 2: pending_resolutions_json injection into key_facts.

Tests:
  - _build_key_facts surfaces last turn's resolutions
  - skips empty pending_resolutions_json
  - formats success vs failure differently
  - caps at 5 entries from last turn
  - still works when pending_resolutions_json is malformed (defensive parse)
"""

import json

import pytest

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    Session as GameSession,
    World,
)
from dzmm.service.game import _build_key_facts


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db_and_seed(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/kf_test.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="黑客",
                         base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
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
        s.add(CharState(session_id=sess.id, stats_json='{"hp":20}', inventory_json="[]"))
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_dice_record(turn: int = 2) -> dict:
    return {
        "turn": turn,
        "kind": "dice",
        "input": {"formula": "2d6+3", "purpose": "伤害"},
        "result": {
            "formula": "2d6+3",
            "rolls": [4, 5],
            "modifier": 3,
            "total": 12,
            "critical_success": False,
            "critical_failure": False,
            "purpose": "伤害",
        },
    }


def _make_skill_success_record(turn: int = 2) -> dict:
    return {
        "turn": turn,
        "kind": "skill",
        "input": {"skill": "潜行", "attribute": "dexterity", "dc": "14"},
        "result": {
            "skill": "潜行",
            "attribute": "dexterity",
            "attribute_value": 16,
            "skill_level": 3,
            "dc": 14,
            "d20": 15,
            "modifier": 3,
            "total": 18,
            "succeeded": True,
            "crit": False,
            "margin": 4,
        },
    }


def _make_skill_failure_record(turn: int = 2) -> dict:
    return {
        "turn": turn,
        "kind": "skill",
        "input": {"skill": "说服", "attribute": "charisma", "dc": "15"},
        "result": {
            "skill": "说服",
            "attribute": "charisma",
            "attribute_value": 10,
            "skill_level": 0,
            "dc": 15,
            "d20": 3,
            "modifier": 0,
            "total": 3,
            "succeeded": False,
            "crit": False,
            "margin": -12,
        },
    }


def _make_item_success_record(turn: int = 2) -> dict:
    return {
        "turn": turn,
        "kind": "item",
        "input": {"item_name": "治疗药水"},
        "result": {
            "item_name": "治疗药水",
            "item_type": "consumable",
            "applied_effects": [{"type": "heal_hp", "amount": 15}],
            "removed_from_inventory": True,
        },
    }


def _make_item_missing_record(turn: int = 2) -> dict:
    return {
        "turn": turn,
        "kind": "item",
        "input": {"item_name": "万能钥匙"},
        "result": {
            "missing": True,
            "item_name": "万能钥匙",
            "warning": "玩家想用「万能钥匙」但背包没有这个物品",
        },
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_key_facts_surfaces_last_turn_resolutions(db_and_seed):
    """_build_key_facts includes '## 上回合机械结算' when there are resolutions."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        # current_turn will be 3; we put records at turn=2 (current_turn - 1)
        records = [_make_dice_record(turn=2), _make_skill_success_record(turn=2)]
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=3)

    assert "上回合机械结算" in kf
    assert "2d6+3" in kf
    assert "潜行" in kf


@pytest.mark.asyncio
async def test_key_facts_skips_empty_pending_resolutions(db_and_seed):
    """No '## 上回合机械结算' section when pending_resolutions_json is empty."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.pending_resolutions_json = "[]"
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=3)

    assert "上回合机械结算" not in kf


@pytest.mark.asyncio
async def test_key_facts_formats_success_vs_failure_differently(db_and_seed):
    """Success shows '成功', failure shows '失败'."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        records = [
            _make_skill_success_record(turn=4),
            _make_skill_failure_record(turn=4),
        ]
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=5)

    assert "成功" in kf
    assert "失败" in kf


@pytest.mark.asyncio
async def test_key_facts_missing_item_shows_warning(db_and_seed):
    """Missing item warning appears in key_facts."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        records = [_make_item_missing_record(turn=1)]
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=2)

    assert "万能钥匙" in kf


@pytest.mark.asyncio
async def test_key_facts_item_success_shows_effect(db_and_seed):
    """Successful item use shows HP effect."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        records = [_make_item_success_record(turn=7)]
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=8)

    assert "治疗药水" in kf
    assert "HP" in kf


@pytest.mark.asyncio
async def test_key_facts_caps_at_five_entries(db_and_seed):
    """Only the last 5 entries from the previous turn appear."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        # 8 dice records all from turn=9
        records = [_make_dice_record(turn=9) for _ in range(8)]
        # Give each a different purpose so we can count them
        for i, r in enumerate(records):
            r["input"]["purpose"] = f"dice_{i}"
            r["result"]["purpose"] = f"dice_{i}"
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=10)

    # Should see at most 5 entries
    # Count occurrences of the purpose prefix
    count = kf.count("dice_")
    assert count <= 5


@pytest.mark.asyncio
async def test_key_facts_skips_wrong_turn_records(db_and_seed):
    """Only records from current_turn - 1 are shown; older ones are skipped."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        records = [
            _make_dice_record(turn=1),   # old — should NOT appear
            _make_dice_record(turn=5),   # current_turn - 1 = 5 — should appear
        ]
        records[0]["input"]["purpose"] = "very_old"
        records[0]["result"]["purpose"] = "very_old"
        records[1]["input"]["purpose"] = "just_right"
        records[1]["result"]["purpose"] = "just_right"
        sess.pending_resolutions_json = json.dumps(records)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=6)

    assert "just_right" in kf
    assert "very_old" not in kf


@pytest.mark.asyncio
async def test_key_facts_handles_malformed_pending_resolutions(db_and_seed):
    """Malformed pending_resolutions_json is silently ignored; no crash."""
    SM, sid = db_and_seed
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.pending_resolutions_json = "NOT VALID JSON !!!"
        await s.commit()

    async with SM() as s:
        # Should not raise; malformed JSON silently gives empty list
        kf = await _build_key_facts(s, sid, current_turn=3)

    # The key_facts string may or may not have '上回合机械结算', but must not crash
    assert isinstance(kf, str)
    assert "上回合机械结算" not in kf
