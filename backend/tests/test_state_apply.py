import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply import apply_tags


@pytest.fixture
async def session_with_state(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y",
                         base_stats_json='{"hp":20,"sanity":15}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id,
                        stats_json='{"hp":20,"sanity":15}',
                        inventory_json="[]"))
        await s.commit()
        yield s, sess.id
    await engine.dispose()


async def test_apply_state_change_updates_stats(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content='{"hp": -5, "sanity": -2}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    stats = json.loads(cs.stats_json)
    assert stats["hp"] == 15
    assert stats["sanity"] == 13


async def test_inventory_add_and_remove(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change",
                      content='{"inventory_add": ["钥匙","小刀"]}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["钥匙", "小刀"]

    tag2 = TagComplete(name="state_change",
                       content='{"inventory_remove": ["钥匙"]}')
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["小刀"]


async def test_npc_update_creates_and_updates(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-10,"state":"警戒"}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    npc = npcs[0]
    assert npc.name == "卫兵长"
    assert npc.favor == -10
    assert npc.state == "警戒"
    assert npc.last_seen_turn == 1

    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-5,"state":"敌对"}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    assert npcs[0].favor == -15
    assert npcs[0].state == "敌对"
    assert npcs[0].last_seen_turn == 2


async def test_apply_tags_skips_malformed_json(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content="not-json-at-all")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.stats_json) == {"hp": 20, "sanity": 15}


async def test_ignores_non_state_tags(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="dice", content="d20=15")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()
