import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)


@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y",
                         base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id,
                           summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id))
        await s.commit()
        yield s, sess.id
    await engine.dispose()


async def test_npc_has_last_initiative_turn(db):
    s, sid = db
    npc = NPC(session_id=sid, name="Test", last_seen_turn=1)
    s.add(npc)
    await s.commit()
    await s.refresh(npc)
    assert npc.last_initiative_turn == 0


import json as _json
from dzmm.service.npc_initiative import find_initiative_npc


async def test_find_returns_none_when_no_npcs(db):
    s, sid = db
    result = await find_initiative_npc(s, sid, current_turn=5)
    assert result is None


async def test_find_returns_none_when_seen_recently(db):
    s, sid = db
    npc = NPC(session_id=sid, name="A", last_seen_turn=4,
              last_initiative_turn=0, favor=30, pinned=True)
    s.add(npc)
    await s.commit()
    # turns_inactive = 5-4 = 1 < 2 → not eligible
    result = await find_initiative_npc(s, sid, current_turn=5)
    assert result is None


async def test_find_returns_npc_when_eligible(db):
    s, sid = db
    npc = NPC(session_id=sid, name="Mei", last_seen_turn=1,
              last_initiative_turn=0, favor=20, pinned=True)
    s.add(npc)
    await s.commit()
    # turns_inactive=5, turns_since_initiative=6, eagerness=10+4=14 > 0
    result = await find_initiative_npc(s, sid, current_turn=6)
    assert result is not None
    assert result.name == "Mei"


async def test_find_respects_cooldown(db):
    s, sid = db
    npc = NPC(session_id=sid, name="B", last_seen_turn=1,
              last_initiative_turn=4, favor=30)
    s.add(npc)
    await s.commit()
    # turns_since_initiative = 7-4 = 3 < 4 cooldown → not eligible
    result = await find_initiative_npc(s, sid, current_turn=7)
    assert result is None


async def test_find_picks_highest_eagerness(db):
    s, sid = db
    low = NPC(session_id=sid, name="Low", last_seen_turn=1,
              last_initiative_turn=0, favor=5, pinned=False)
    high = NPC(session_id=sid, name="High", last_seen_turn=1,
               last_initiative_turn=0, favor=30, pinned=True)
    s.add_all([low, high])
    await s.commit()
    result = await find_initiative_npc(s, sid, current_turn=8)
    assert result.name == "High"


async def test_find_returns_none_when_favor_zero_and_not_pinned(db):
    s, sid = db
    npc = NPC(session_id=sid, name="C", last_seen_turn=1,
              last_initiative_turn=0, favor=0, pinned=False)
    s.add(npc)
    await s.commit()
    # eagerness = 0 + 0 + 0 = 0, not > 0 → not eligible
    result = await find_initiative_npc(s, sid, current_turn=8)
    assert result is None
