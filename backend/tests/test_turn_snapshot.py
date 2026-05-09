"""v0.10.5: turn-effect rollback via state snapshots."""
import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    CharState, Character, ModelConfig, NPC,
    Session as GameSession, World,
)
from dzmm.service.turn_snapshot import take_snapshot, restore_snapshot


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


async def _seed(sm) -> int:
    async with sm() as s:
        w = World(name="W", content_md="x")
        s.add(w); await s.flush()
        c = Character(world_id=w.id, name="C", profile_md="p",
                      base_stats_json='{"hp":20}')
        m = ModelConfig(name="m", type="ollama", base_url="x", model_name="y")
        s.add_all([c, m]); await s.flush()
        sess = GameSession(name="t", world_id=w.id, character_id=c.id,
                           gm_model_config_id=m.id, summarizer_model_config_id=m.id,
                           turn_count=0, doom_score=0)
        s.add(sess); await s.flush()
        s.add(CharState(session_id=sess.id, stats_json='{"hp":20}', inventory_json='[]'))
        s.add(NPC(session_id=sess.id, name="丽莎", favor=0, last_seen_turn=0))
        await s.commit()
        return sess.id


async def test_snapshot_then_restore_reverts_stat_change(session_maker):
    sid = await _seed(session_maker)
    async with session_maker() as s:
        snap = await take_snapshot(s, sid)
        # mutate state (simulating a turn's effects)
        cs = (await s.execute(select(CharState).where(CharState.session_id == sid))).scalar_one()
        cs.stats_json = '{"hp": 5}'
        sess = await s.get(GameSession, sid)
        sess.doom_score = 50
        npc = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalar_one()
        npc.favor = -30
        await s.commit()

        # restore
        await restore_snapshot(s, sid, snap)
        await s.commit()

        cs2 = (await s.execute(select(CharState).where(CharState.session_id == sid))).scalar_one()
        sess2 = await s.get(GameSession, sid)
        npc2 = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalar_one()
    assert cs2.stats_json == '{"hp":20}'
    assert sess2.doom_score == 0
    assert npc2.favor == 0


async def test_snapshot_restore_deletes_npcs_created_this_turn(session_maker):
    sid = await _seed(session_maker)
    async with session_maker() as s:
        snap = await take_snapshot(s, sid)
        # Create a new NPC mid-turn
        s.add(NPC(session_id=sid, name="新角色", favor=10, last_seen_turn=1))
        await s.commit()

        before = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalars().all()
        assert len(before) == 2

        await restore_snapshot(s, sid, snap)
        await s.commit()
        after = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalars().all()
    assert len(after) == 1
    assert after[0].name == "丽莎"


async def test_snapshot_restore_handles_empty_snapshot(session_maker):
    """Empty snap = no-op, doesn't crash."""
    sid = await _seed(session_maker)
    async with session_maker() as s:
        await restore_snapshot(s, sid, {})
        await s.commit()
