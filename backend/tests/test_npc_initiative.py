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
