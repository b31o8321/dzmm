"""
Tests for v0.15.1 C4+: 8-turn stall auto-advance.

When turns_since_progress >= 8 and there is an active Screenplay with pending
main events, _build_key_facts must:
  - append the first pending event to completed_events_json
  - emit a "系统自动推进" note (not a 剧情强推 warning) in the returned key_facts

When turns_since_progress is 3-7 the existing warning behaviour should remain.
"""

import json
import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig,
    Session as GameSession, Screenplay, World,
)
from dzmm.service.game import _build_key_facts


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _chapters_json(events: list[str]) -> str:
    """One-chapter screenplay with the given list of event strings."""
    return json.dumps([{"title": "第一章", "main_events": events}])


def _completed_json(entries: list[dict]) -> str:
    return json.dumps(entries)


# ---------------------------------------------------------------------------
# shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/stall.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark", rules_json='{"mode":"light"}')
        char = Character(world=world, name="Hero", profile_md="", base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(
            name="test",
            world_id=world.id,
            character_id=char.id,
            gm_model_config_id=cfg.id,
            summarizer_model_config_id=cfg.id,
        )
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id, stats_json='{"hp":20}', inventory_json="[]"))
        await s.commit()
        yield SM, sess.id, world.id, char.id, cfg.id
    await engine.dispose()


async def _seed_screenplay(SM, sid, chapters_json_str, completed_json_str="[]", current_chapter=1):
    """Add a Screenplay to the session and return its id."""
    async with SM() as s:
        sp = Screenplay(
            session_id=sid,
            title="测试剧本",
            chapters_json=chapters_json_str,
            completed_events_json=completed_json_str,
            current_chapter=current_chapter,
            ending_md="",
        )
        s.add(sp)
        await s.flush()
        sess = await s.get(GameSession, sid)
        sess.screenplay_id = sp.id
        await s.commit()
        return sp.id


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

async def test_stall_under_8_turns_only_warns(db):
    """turns_since_progress=5 → existing warning emitted; completed_events NOT mutated."""
    SM, sid, *_ = db
    sp_id = await _seed_screenplay(SM, sid, _chapters_json(["事件A", "事件B"]))

    # completed_events is empty → turns_since_progress = current_turn - 0 = 5
    current_turn = 5
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)
        # Key facts should contain the 3-turn warning text, NOT the auto-advance note
        assert "剧情强推" in kf or "极度紧急" in kf
        assert "系统自动推进" not in kf
        sp = await s.get(Screenplay, sp_id)
        completed = json.loads(sp.completed_events_json)
    assert completed == []


async def test_stall_8_turns_auto_completes_first_pending(db):
    """turns_since_progress=8 → completed_events_json gets one new entry."""
    SM, sid, *_ = db
    sp_id = await _seed_screenplay(SM, sid, _chapters_json(["事件A", "事件B"]))

    current_turn = 8  # last_progress_turn = 0, turns_since_progress = 8
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)
        assert "系统自动推进" in kf
        sp = await s.get(Screenplay, sp_id)
        completed = json.loads(sp.completed_events_json)

    assert len(completed) == 1
    entry = completed[0]
    assert entry["chapter"] == 1
    assert entry["event_idx"] == 0
    assert entry["type"] == "main"
    assert entry["turn"] == current_turn
    assert entry["auto"] is True


async def test_auto_advance_picks_first_pending_event(db):
    """events[0] already done, events[1] pending, events[2] pending → picks 1."""
    SM, sid, *_ = db
    chapters = _chapters_json(["事件A", "事件B", "事件C"])
    already_done = _completed_json([
        {"chapter": 1, "event_idx": 0, "type": "main", "turn": 2}
    ])
    sp_id = await _seed_screenplay(SM, sid, chapters, already_done)

    current_turn = 10  # last_progress_turn = 2, turns_since_progress = 8
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)
        assert "系统自动推进" in kf
        sp = await s.get(Screenplay, sp_id)
        completed = json.loads(sp.completed_events_json)

    # Should have original entry + new auto entry
    assert len(completed) == 2
    auto = completed[-1]
    assert auto["event_idx"] == 1  # first pending after idx 0
    assert auto["auto"] is True


async def test_no_pending_events_in_chapter_no_op(db):
    """All events already done → no auto-advance, no crash."""
    SM, sid, *_ = db
    chapters = _chapters_json(["事件A", "事件B"])
    all_done = _completed_json([
        {"chapter": 1, "event_idx": 0, "type": "main", "turn": 1},
        {"chapter": 1, "event_idx": 1, "type": "main", "turn": 2},
    ])
    sp_id = await _seed_screenplay(SM, sid, chapters, all_done)

    current_turn = 10
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)
        sp = await s.get(Screenplay, sp_id)
        completed = json.loads(sp.completed_events_json)

    # No auto-advance note, no new entries added
    assert "系统自动推进" not in kf
    assert len(completed) == 2


async def test_no_active_screenplay_no_op(db):
    """Legacy session with no screenplay → no crash, normal key_facts returned."""
    SM, sid, *_ = db
    # Do NOT add a screenplay — sess.screenplay_id stays None

    current_turn = 15
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)

    # Should return something without crashing
    assert isinstance(kf, str)
    assert "系统自动推进" not in kf


async def test_auto_advance_emits_system_note_in_key_facts(db):
    """Check exact rendered text contains '系统自动推进' when auto-firing."""
    SM, sid, *_ = db
    sp_id = await _seed_screenplay(SM, sid, _chapters_json(["联系线人", "获取证据"]))

    current_turn = 8
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn)

    assert "系统自动推进" in kf
    assert "8 回合无进度" in kf
    assert "联系线人" in kf  # event description appears in the note
